/**
 * 解析器冒烟测试：node tools/test-parser.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const base = path.join(__dirname, '..');
const sandbox = { globalThis: {}, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const file of [
  'src/shared/defaults.js',
  'src/content/json-parser.js'
]) {
  const code = fs.readFileSync(path.join(base, file), 'utf8');
  vm.runInContext(code, sandbox, { filename: file });
}

const NS = sandbox.__EDGE_JSON_FORMATTER__;
const parser = NS.parser;

let pass = 0;
let fail = 0;

function check(name, fn) {
  try {
    fn();
    pass++;
    console.log('  \u2713 ' + name);
  } catch (err) {
    fail++;
    console.log('  \u2717 ' + name + '\n      ' + err.message);
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed');
}

const SAMPLE = fs.readFileSync(path.join(base, 'tools', 'sample.json'), 'utf8');

console.log('解析与保真');

check('能解析示例订单 JSON', () => {
  const res = parser.parse(SAMPLE);
  assert(res.root.type === 'object');
});

check('大整数场景：raw 与源码逐字一致', () => {
  const res = parser.parse(SAMPLE);
  const found = [];
  parser.walk(res.root, (n) => {
    if (n.keyNode && n.keyNode.value === 'orderId') found.push(n);
  });
  assert(found.length === 1, 'orderId 命中数 = ' + found.length);
  assert(found[0].type === 'string', 'orderId 应为字符串');
  assert(found[0].raw === '"600653836507516928"', 'raw 不一致: ' + found[0].raw);
  assert(found[0].path === '$.data.list[0].orderId', '路径 = ' + found[0].path);
});

check('超出安全整数范围的数字也保留原文', () => {
  const res = parser.parse('{"big":600653836507516928}');
  const v = res.root.entries[0].value;
  assert(v.raw === '600653836507516928', 'raw = ' + v.raw);
});

check('整个文档的 raw 可无损还原原始数据', () => {
  const res = parser.parse(SAMPLE);
  assert(res.root.raw === SAMPLE.trim(), '根节点 raw 与原文不一致');
});

check('数字保留原始字面量', () => {
  const res = parser.parse('{"t":1784173433013}');
  assert(res.root.entries[0].value.raw === '1784173433013');
});

check('保留转义：\\u 序列原样存在于 raw 中', () => {
  const res = parser.parse('{"k":"\\u4e2d\\u6587"}');
  const v = res.root.entries[0].value;
  assert(v.raw === '"\\u4e2d\\u6587"', 'raw = ' + v.raw);
  assert(v.value === '中文', '解码值 = ' + v.value);
});

check('保留转义：\\n 原样存在于 raw 中', () => {
  const res = parser.parse('{"k":"a\\nb"}');
  const v = res.root.entries[0].value;
  assert(v.raw === '"a\\nb"', 'raw = ' + v.raw);
  assert(v.value === 'a\nb', '解码值错误');
});

console.log('路径与遍历');

check('walk 生成点号路径', () => {
  const res = parser.parse(SAMPLE);
  const paths = [];
  parser.walk(res.root, (n) => paths.push(n.path));
  assert(paths.includes('$.data.list[0].orderId'), '缺少预期路径，实际：' + paths.slice(0, 6).join(', '));
});

check('walk 生成方括号路径（键名含特殊字符）', () => {
  const res = parser.parse('{"a-b":{"c d":1}}');
  const paths = [];
  parser.walk(res.root, (n) => paths.push(n.path));
  assert(paths.includes('$["a-b"]["c d"]'), '实际：' + paths.join(', '));
});

check('stats 统计节点数与深度', () => {
  const res = parser.parse('{"a":{"b":{"c":1}}}');
  const s = parser.stats(res.root);
  assert(s.count === 4, 'count = ' + s.count);
  assert(s.depth === 3, 'depth = ' + s.depth);
});

console.log('错误定位');

check('语法错误带行列信息', () => {
  let err = null;
  try {
    parser.parse('{\n  "a": 1,\n  "b" 2\n}');
  } catch (e) {
    err = e;
  }
  assert(err, '应当抛错');
  assert(err.line === 3, 'line = ' + err.line);
  assert(typeof err.column === 'number' && err.column > 1, 'column = ' + err.column);
});

check('缺少右括号能报错', () => {
  let err = null;
  try { parser.parse('{"a":1'); } catch (e) { err = e; }
  assert(err, '应当抛错');
});

console.log('宽松模式');

check('relax 去除注释与尾随逗号', () => {
  const text = '{\n // 注释\n "a": 1,\n /* 块注释 */ "b": [1, 2,],\n}';
  const res = parser.parse(text, { lenient: true });
  assert(res.lenient === true, '应标记为宽松解析');
  assert(res.root.entries.length === 2, '字段数 = ' + res.root.entries.length);
});

check('relax 处理单引号与裸键', () => {
  const text = "{ a: 'hello', b: 2 }";
  const res = parser.parse(text, { lenient: true });
  assert(res.root.entries[0].keyNode.value === 'a');
  assert(res.root.entries[0].value.value === 'hello');
});

check('relax 不误伤字符串内部的冒号与逗号', () => {
  const text = '{"note":"a, b: c","n":1}';
  const relaxed = parser.relax(text);
  const res = parser.parse(relaxed);
  assert(res.root.entries[0].value.value === 'a, b: c', '实际：' + res.root.entries[0].value.value);
});

console.log('边界情况');

check('空对象与空数组', () => {
  const res = parser.parse('{"o":{},"a":[]}');
  assert(res.root.entries[0].value.entries.length === 0);
  assert(res.root.entries[1].value.items.length === 0);
});

check('顶层为基本类型', () => {
  assert(parser.parse('"hi"').root.value === 'hi');
  assert(parser.parse('42').root.value === 42);
  assert(parser.parse('null').root.type === 'null');
});

check('BOM 不影响解析', () => {
  const res = parser.parse('\uFEFF{"a":1}');
  assert(res.root.entries.length === 1);
});

check('普通 JSON.parse 能解析的都能解析', () => {
  const samples = [
    '[]', '{}', '[1,2,3]', '{"a":[{"b":null}]}',
    '{"s":"\\"quoted\\""}', '{"u":"\\ud83d\\ude00"}',
    '{"e":1e10,"n":-0.5}', '  {"x" : true }  '
  ];
  for (const s of samples) {
    JSON.parse(s);
    parser.parse(s);
  }
});

console.log('\n' + pass + ' 通过, ' + fail + ' 失败');
process.exit(fail ? 1 : 0);
