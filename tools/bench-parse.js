/**
 * 22MB 快路径各阶段拆解：守卫 / 原生解析 / 统计。
 * 用来盯住「哪一段又变慢了」。
 *
 * 运行：node tools/bench-parse.js [文件]
 */
'use strict';
const fs = require('fs');
const path = require('path');

const base = path.join(__dirname, '..');
const fakeGlobal = {};         // 见 test-fastpath.js：避开 vm 沙箱的性能失真
for (const f of ['src/shared/defaults.js', 'src/content/json-parser.js']) {
  new Function('globalThis', fs.readFileSync(path.join(base, f), 'utf8'))(fakeGlobal);
}
const parser = fakeGlobal.__EDGE_JSON_FORMATTER__.parser;

const file = process.argv[2] || path.join(__dirname, 'fixtures', 'big-20mb.json');
const text = fs.readFileSync(file, 'utf8');
console.log('文件 ' + path.basename(file) + '  ' +
  (text.length / 1048576).toFixed(2) + ' MB  ' + text.split('\n').length + ' 行\n');

function best(fn, label, reps) {
  reps = reps || 3;
  let b = Infinity, r;
  for (let i = 0; i < reps; i++) {
    const t = process.hrtime.bigint();
    r = fn();
    const d = Number(process.hrtime.bigint() - t) / 1e6;
    if (d < b) b = d;
  }
  console.log('  ' + label.padEnd(34) + b.toFixed(1) + ' ms');
  return r;
}

// 与源码同构的守卫，单独计时
const RISKY = /[0-9]{16}/;
function guard(text) {
  const n = text.length;
  let nb = text.indexOf('\\');
  let i = 0;
  while (i < n) {
    let q = text.indexOf('"', i);
    if (q === -1) q = n;
    if (q - i > 15 && RISKY.test(text.slice(i, q))) return true;
    if (q >= n) break;
    let s = q + 1, e;
    for (;;) {
      while (nb !== -1 && nb < s) nb = text.indexOf('\\', nb + 1);
      const dq = text.indexOf('"', s);
      if (nb !== -1 && (dq === -1 || nb < dq)) {
        const ec = text.charAt(nb + 1);
        if (ec === 'u' || ec === '/') return true;
        s = nb + 2; continue;
      }
      if (dq === -1) { e = n; break; }
      e = dq; break;
    }
    i = e + 1;
  }
  return false;
}

// 只切字符串、不做数字检查的裸基线，用来判断守卫的开销来自哪里
function splitOnly(text) {
  const n = text.length;
  let nb = text.indexOf('\\');
  let i = 0;
  while (i < n) {
    let q = text.indexOf('"', i);
    if (q === -1) q = n;
    if (q >= n) break;
    let s = q + 1, e;
    for (;;) {
      while (nb !== -1 && nb < s) nb = text.indexOf('\\', nb + 1);
      const dq = text.indexOf('"', s);
      if (nb !== -1 && (dq === -1 || nb < dq)) { s = nb + 2; continue; }
      if (dq === -1) { e = n; break; }
      e = dq; break;
    }
    i = e + 1;
  }
  return false;
}

best(() => guard(text), '守卫 hasRawRisk');
best(() => splitOnly(text), '  其中：仅按引号切段');
best(() => RISKY.test(text) && 0, '  参考：全文正则 /[0-9]{16}/');
const native = best(() => JSON.parse(text), 'JSON.parse 原生');

// 统计（含键计数 + 键序校验）——等价于源码里的 measureNative
function measure(v, meta, checkKeys) {
  const stack = [v], depths = [0];
  while (stack.length) {
    const cur = stack.pop(), d = depths.pop();
    meta.count++;
    if (d > meta.depth) meta.depth = d;
    if (Array.isArray(cur)) {
      for (let i = cur.length - 1; i >= 0; i--) { stack.push(cur[i]); depths.push(d + 1); }
    } else if (cur && typeof cur === 'object') {
      const ks = Object.keys(cur);
      meta.count += ks.length;
      for (let j = ks.length - 1; j >= 0; j--) {
        if (checkKeys && /^\d/.test(ks[j])) throw new Error('fallback');
        stack.push(cur[ks[j]]); depths.push(d + 1);
      }
    }
  }
}
const m = { count: 0, depth: 0 };
best(() => measure(native, m, true), '统计 + 键序校验');
console.log('    节点 ' + m.count.toLocaleString() + ' 深度 ' + m.depth);

console.log('\n端到端：');
best(() => parser.parse(text), '快路径 parse()');
const slow = best(() => parser.parse(text, { noFastPath: true }), '手写解析器 parse()');
console.log('    节点 ' + slow.count.toLocaleString() + ' 深度 ' + slow.depth);
