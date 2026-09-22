#!/usr/bin/env node
/**
 * test-bigview.js —— 大文档视图排版器测试。
 *
 * 在 Node 里直接加载 src/content/json-parser.js + src/content/bigview.js
 * （两者都是纯 JS，不碰 DOM），然后拿 NS.bigViewPrettify 跟原生
 * JSON.stringify 逐字节比对，并单测保真路径（大整数 / \uXXXX / \/）。
 *
 * 用法：node tools/test-bigview.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');

// 造一个最小的宿主环境：bigview.js 只依赖 globalThis + NS.parser
const sandbox = { console, performance, JSON, Object, Array, String, Number, parseInt, RegExp };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const f of ['src/content/json-parser.js', 'src/content/bigview.js']) {
  const code = fs.readFileSync(path.join(ROOT, f), 'utf8');
  vm.runInContext(code, sandbox, { filename: f });
}

const NS = sandbox.__EDGE_JSON_FORMATTER__;
if (!NS || !NS.bigViewPrettify) throw new Error('bigview.js 没有导出 bigViewPrettify');

let pass = 0;
let fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (extra ? '\n      ' + extra : '')); }
}

/* ---------- 1. 与原生 stringify 逐字节一致（安全文本 → 快路径） ---------- */
console.log('\n[1] 快路径：与 JSON.stringify(v,null,N) 逐字节一致');

const samples = [
  ['标量', '42'],
  ['字符串', '"hello"'],
  ['空对象', '{}'],
  ['空数组', '[]'],
  ['空容器带空白', '{ }'],
  ['嵌套空', '{"a":{},"b":[]}'],
  ['简单对象', '{"a":1,"b":"x","c":true,"d":null}'],
  ['数组', '[1,2,3,[4,5]]'],
  ['深层', '{"a":{"b":{"c":{"d":[1,{"e":2}]}}}}'],
  ['已经排好版的', '{\n  "a": 1,\n  "b": [\n    2,\n    3\n  ]\n}'],
  ['多余空白', '  {  "a" : 1 ,  "b" : [ 2 , 3 ]  }  '],
  ['负数与科学计数', '[-1,1.5,1e3,-0.25]'],
  ['含转义引号', '{"s":"say \\"hi\\""}'],
  ['含换行转义', '{"s":"a\\nb\\tc"}'],
  ['中文', '{"名称":"测试","值":[1,2]}'],
  ['Unicode 转义', '{"s":"\\u4e2d\\u6587"}'],
  ['斜杠转义', '{"url":"a\\/b"}'],
  ['大整数', '{"id":12345678901234567890}'],
];

for (const [name, src] of samples) {
  // 命中原文风险的样本必然走保真路径，不能拿原生 stringify 当基准
  if (NS.parser.hasRawRisk(src)) continue;
  for (const indent of [2, 4]) {
    const r = NS.bigViewPrettify(src, indent, false);
    const v = JSON.parse(src);
    const want = JSON.stringify(v, null, ' '.repeat(indent));
    check(name + ' (indent=' + indent + ')', r.text === want,
      'got  ' + JSON.stringify(r.text) + '\n      want ' + JSON.stringify(want));
  }
}

/* ---------- 2. 保真路径：大整数 / \uXXXX / \/ 一字不改 ---------- */
console.log('\n[2] 保真路径：原文字节级保留');

const fidelity = [
  ['大整数不被截断', '{"id":12345678901234567890}', '12345678901234567890'],
  ['Unicode 转义保留', '{"s":"\\u4e2d"}', '\\u4e2d'],
  ['斜杠转义保留', '{"u":"a\\/b"}', 'a\\/b'],
];

for (const [name, src, needle] of fidelity) {
  const r = NS.bigViewPrettify(src, 2, false);
  check(name, r.ok && r.text.indexOf(needle) !== -1 && r.exact === false,
    'ok=' + r.ok + ' exact=' + r.exact + ' text=' + JSON.stringify(r.text));
}

/* 对照：走快路径时确实会「不保真」（说明两条路的分工是真实存在的） */
{
  const r = NS.bigViewPrettify('{"id":12345678901234567890}', 2, false);
  check('风险文本不会走快路径（否则大整数会变成 12345678901234567000）',
    r.text.indexOf('12345678901234567890') !== -1, JSON.stringify(r.text));
}

/* ---------- 3. compact ---------- */
console.log('\n[3] compact：单行输出');
for (const [name, src] of samples.slice(6)) {
  const r = NS.bigViewPrettify(src, 2, true);
  let want;
  try { want = JSON.stringify(JSON.parse(src)); } catch (e) { continue; }
  // 保真路径的紧凑输出不重排字符串，因此仅在快路径下与原生完全一致
  if (r.exact) check(name + ' compact', r.text === want, JSON.stringify(r.text));
}

/* ---------- 4. 非法 JSON：ok=false 但仍给出尽力排版 ---------- */
console.log('\n[4] 非法 JSON');
{
  const r = NS.bigViewPrettify('{"a":1,}', 2, false);
  check('尾随逗号 → ok=false', r.ok === false, 'ok=' + r.ok);
  check('尾随逗号 → 仍有排版输出', r.text.length > 0 && r.text.indexOf('\n') !== -1, JSON.stringify(r.text));
}
{
  const r = NS.bigViewPrettify('{"a":1', 2, false);
  check('缺右括号 → ok=false', r.ok === false, 'ok=' + r.ok);
  check('缺右括号 → 报告括号问题', /括号/.test(r.problem || ''), 'problem=' + r.problem);
}
{
  const r = NS.bigViewPrettify('{"a":"unterminated}', 2, false);
  check('字符串未收尾 → ok=false', r.ok === false, 'ok=' + r.ok);
}
{
  const r = NS.bigViewPrettify('{"a":"line\nbreak"}', 2, false);
  check('字符串内裸换行 → ok=false', r.ok === false, 'ok=' + r.ok);
}

/* ---------- 5. 幂等：排版结果再排一次不变 ---------- */
console.log('\n[5] 幂等');
for (const [name, src] of samples) {
  let a;
  try { a = NS.bigViewPrettify(src, 2, false).text; } catch (e) { continue; }
  const b = NS.bigViewPrettify(a, 2, false).text;
  check(name + ' 二次排版不变', a === b, 'a=' + JSON.stringify(a.slice(0, 80)) + '\n      b=' + JSON.stringify(b.slice(0, 80)));
}

console.log('\n' + (fail ? '✗' : '✓') + ' 通过 ' + pass + ' / 失败 ' + fail);
process.exit(fail ? 1 : 0);
