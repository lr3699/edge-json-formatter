#!/usr/bin/env node
/**
 * bench-bigformat.js —— 大文档视图排版耗时基准。
 *
 * 直接加载 src/content/json-parser.js + src/content/bigview.js，测
 * NS.bigViewPrettify 的两条路径：
 *   快路径（原生 JSON.parse + JSON.stringify）—— 无原文风险时走这条
 *   保真路径（字符扫描，不建对象树、不重新序列化）—— 有转义/大整数时走这条
 *
 * 用法：node tools/bench-bigformat.js [目标MB]
 *
 * 历史结论（决定 bigview.js 为什么写成两条路）：
 *   最初实现过「逐字符 push 到数组」的扫描器，比原生慢 60%（4500 万个数组元素
 *   本身的开销）；改成「按块 slice + 最后 join」后才与原生持平。两条路速度相当，
 *   差别只在保真，所以用 hasRawRisk 分流即可，不需要为了速度牺牲大整数。
 */
'use strict';

const vm = require('vm');
const fs = require('fs');
const path = require('path');

const MB = parseInt(process.argv[2], 10) || 20;
const TARGET = MB * 1024 * 1024;

/* ---------- 造样本：贴近真实接口返回（对象数组 + 长字符串 + 嵌套） ---------- */
function makeSample(targetBytes) {
  const rows = [];
  let size = 0;
  let i = 0;
  const pad = 'x'.repeat(120);
  while (size < targetBytes) {
    rows.push({
      id: i,
      uid: 'u_' + (0x100000 + i).toString(36),
      name: '用户' + i,
      email: 'user' + i + '@example.com',
      active: i % 3 !== 0,
      score: Math.round((i * 7919) % 100000) / 100,
      tags: ['alpha', 'beta', 'gamma', 'delta'],
      meta: { created: '2026-0' + ((i % 9) + 1) + '-1' + (i % 9), note: pad, n: i % 17 },
      nested: { deep: { a: i, b: [i, i + 1, i + 2], c: null } }
    });
    size += 260;
    i++;
  }
  return JSON.stringify(rows);
}

/* ---------- 加载真实模块 ---------- */
const sandbox = { console, performance, JSON, Object, Array, String, Number, parseInt, RegExp };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const f of ['src/content/json-parser.js', 'src/content/bigview.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', f), 'utf8'), sandbox, { filename: f });
}
const NS = sandbox.__EDGE_JSON_FORMATTER__;
const P = NS.bigViewPrettify;

const text = makeSample(TARGET);
// 风险样本：把每个 id 换成 20 位雪花号，强制走保真扫描路径
const riskyText = text.replace(/"id":\d+/g, '"id":12345678901234567890');

console.log('安全样本 ' + (text.length / 1024 / 1024).toFixed(1) + ' MB，hasRawRisk = ' +
            NS.parser.hasRawRisk(text));
console.log('风险样本 ' + (riskyText.length / 1024 / 1024).toFixed(1) + ' MB，hasRawRisk = ' +
            NS.parser.hasRawRisk(riskyText) + '\n');

for (const pair of [['安全 快路径  ', text], ['风险 保真路径', riskyText]]) {
  for (let r = 1; r <= 2; r++) {
    const t0 = performance.now();
    const res = P(pair[1], 2, false);
    const ms = performance.now() - t0;
    console.log(pair[0] + ' 第' + r + '轮：' + (ms.toFixed(0) + 'ms').padEnd(7) +
                ' exact=' + String(res.exact).padEnd(6) + ' ok=' + String(res.ok).padEnd(6) +
                ' 输出 ' + (res.text.length / 1024 / 1024).toFixed(1) + ' MB' +
                '  ' + res.text.split('\n').length.toLocaleString('en-US') + ' 行');
  }
}

/* ---------- 保真校验：风险路径必须逐字保留大整数 ---------- */
const risky = P(riskyText, 2, false);
console.log('\n保真校验：输出里 12345678901234567890 出现 ' +
            (risky.text.match(/12345678901234567890/g) || []).length + ' 次（应为 ' +
            (riskyText.match(/12345678901234567890/g) || []).length + ' 次）');
