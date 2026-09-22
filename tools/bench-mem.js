/**
 * 量一下 22MB 文档在「惰性树」下的真实内存占用，以及把可见行摊平的成本。
 * 运行：node --expose-gc tools/bench-mem.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const base = path.join(__dirname, '..');
const fakeGlobal = {};
for (const f of ['src/shared/defaults.js', 'src/content/json-parser.js']) {
  new Function('globalThis', fs.readFileSync(path.join(base, f), 'utf8'))(fakeGlobal);
}
const parser = fakeGlobal.__EDGE_JSON_FORMATTER__.parser;

const file = process.argv[2] || path.join(__dirname, 'fixtures', 'big-20mb.json');
const text = fs.readFileSync(file, 'utf8');
const mb = (n) => (n / 1048576).toFixed(1) + ' MB';

function gc() { if (global.gc) { global.gc(); global.gc(); } }
function heap() { gc(); return process.memoryUsage().heapUsed; }

console.log('文件 ' + path.basename(file) + '  ' + mb(text.length) + '  ' +
  text.split('\n').length.toLocaleString() + ' 行');

const h0 = heap();
console.log('  读入文本后堆        ' + mb(h0));

const t0 = process.hrtime.bigint();
const res = parser.parse(text);
const t1 = process.hrtime.bigint();
console.log('  parse() 耗时        ' + (Number(t1 - t0) / 1e6).toFixed(1) + ' ms');
console.log('  报告节点数          ' + res.count.toLocaleString() + '  深度 ' + res.depth);

const h1 = heap();
console.log('  parse 后堆          ' + mb(h1) + '   （净增 ' + mb(h1 - h0) + '）');

// 摊平：全展开时「可见行」有多少、建成扁平表要多久、占多少内存
const t2 = process.hrtime.bigint();
const flatIds = [];
const flatDepth = [];
let rows = 0;
parser.walk(res.root, function (node) {
  rows++;
  flatIds.push(node);
  flatDepth.push(node.depth);
});
const t3 = process.hrtime.bigint();
console.log('  全展开可见行数      ' + rows.toLocaleString() +
            '  （摊平耗时 ' + (Number(t3 - t2) / 1e6).toFixed(1) + ' ms）');

const h2 = heap();
console.log('  摊平后堆            ' + mb(h2) + '   （净增 ' + mb(h2 - h1) + '）');
console.log('');
console.log('  → 结论：DOM 里只挂 ~50 行，滚动靠「扁平表下标 → 窗口」映射；');
console.log('    全展开也只多花 ' + mb(h2 - h1) + ' 与 ' +
            (Number(t3 - t2) / 1e6).toFixed(0) + ' ms，与 DOM 无关。');
