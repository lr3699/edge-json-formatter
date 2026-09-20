// 诊断：定位严格解析路径的二次复杂度热点。
// 结果写 _diag.txt（PowerShell 管道会吞 stderr，不走终端）。
'use strict';
const fs = require('fs');
const path = require('path');
const LINES = [];
function log(s) { LINES.push(s); }
function flush() { fs.writeFileSync(path.join(__dirname, '_diag.txt'), LINES.join('\n'), 'utf8'); }
process.on('exit', flush);

globalThis.__EDGE_JSON_FORMATTER__ = {};
const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'content', 'json-parser.js'), 'utf8');
new Function(src)();
const parser = globalThis.__EDGE_JSON_FORMATTER__.parser;

function timeIt(label, fn) {
  const t0 = process.hrtime.bigint();
  fn();
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  log(`${label.padEnd(44)} ${ms.toFixed(1).padStart(10)} ms`);
}

// 1) 纯数字数组：无字符串、无对象
const arr1 = JSON.stringify(Array.from({ length: 50000 }, (_, i) => i));
log(`纯数字数组 ${(arr1.length / 1024).toFixed(0)} KB, 5 万节点`);
timeIt('  parse', () => parser.parse(arr1));

// 2) 字符串数组：只有字符串
const arr2 = JSON.stringify(Array.from({ length: 50000 }, (_, i) => '值-' + i));
log(`字符串数组 ${(arr2.length / 1024).toFixed(0)} KB, 5 万节点`);
timeIt('  parse', () => parser.parse(arr2));

// 3) 对象数组：键多值短
const obj3 = JSON.stringify(Array.from({ length: 20000 }, (_, i) => ({ a: i, b: 'x' + i })));
log(`小对象数组 ${(obj3.length / 1024).toFixed(0)} KB, 6 万节点`);
timeIt('  parse', () => parser.parse(obj3));

// 4) 单个大对象：10 万个短键值对
const pairs = [];
for (let i = 0; i < 100000; i++) pairs.push('"k' + i + '":' + i);
const obj4 = '{' + pairs.join(',') + '}';
log(`单一大对象 ${(obj4.length / 1024).toFixed(0)} KB, 10 万节点`);
timeIt('  parse', () => parser.parse(obj4));

// 5) walk/stats 单独计时（不在 parse 里）
const r = parser.parse(obj3);
timeIt('  walk/stats（上面 obj3）', () => parser.stats(r.root));

log('\n诊断完成。');
