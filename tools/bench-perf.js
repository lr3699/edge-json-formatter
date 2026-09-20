/**
 * 大 JSON 性能基准：验证卡死修复。
 * 用法：node tools/bench-perf.js
 * 结果直接写入 tools/_bench_result.txt（PowerShell 管道会吞 stderr，不走终端）。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const LINES = [];
function log(s) { LINES.push(s); }
process.on('uncaughtException', function (e) {
  log('未捕获异常: ' + (e && e.stack || e));
  flush();
  process.exit(1);
});
process.on('exit', function () {
  flush();
});

// 加载解析器（与扩展内一致的全局挂载方式）
globalThis.__EDGE_JSON_FORMATTER__ = {};
const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'content', 'json-parser.js'), 'utf8');
new Function(src)(); // 以普通脚本形式执行，模拟 content script 环境
const parser = globalThis.__EDGE_JSON_FORMATTER__.parser;

function makeBigJson(nItems) {
  const parts = [];
  for (let i = 0; i < nItems; i++) {
    parts.push(`{"id":${i},"name":"项目-${i}","score":${(i * 7) % 100}.5,"ok":${i % 2 === 0},"tags":["a","b","c"],"meta":{"ts":1784173433013,"ref":${9007199254740993 + i}}}`);
  }
  return '[' + parts.join(',\n') + ']';
}

function bench(label, fn) {
  const t0 = process.hrtime.bigint();
  const r = fn();
  const t1 = process.hrtime.bigint();
  const ms = Number(t1 - t0) / 1e6;
  log(`${label.padEnd(38)} ${ms.toFixed(1).padStart(9)} ms`);
  flush();
  return r;
}

function flush() {
  fs.writeFileSync(path.join(__dirname, '_bench_child.txt'), LINES.join('\n'), 'utf8');
}

const N = parseInt(process.env.BENCH_N || '100000', 10);
const big = makeBigJson(N);
log(`样本：${N} 项数组，约 ${(big.length / 1024 / 1024).toFixed(1)} MB\n`);
flush();

const res = bench('parse() 严格模式', () => parser.parse(big));
log(`  节点数 ${parser.stats(res.root).count}\n`);
flush();

// 宽松路径：故意制造需要 relax 的输入（裸键 + 注释）
const lenient = big.replace(/^/, '// top comment\n').replace(/\{"id":/g, '{id:');
bench('parse() 宽松模式（relax 路径）', () => parser.parse(lenient, { lenient: true }));

// 单独计时 relax（O(n²) 修复点）
bench('relax() 单独', () => parser.relax(lenient));

// 模拟 readString 的长字符串场景：一个大字符串值
const bigStr = '{"data":"' + 'x'.repeat(5 * 1024 * 1024) + '"}';
bench('parse() 单个 5MB 长字符串', () => parser.parse(bigStr));

log('\n全部完成。');
flush();
