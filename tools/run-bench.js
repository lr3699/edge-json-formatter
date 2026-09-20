// 包装器：以子进程运行 bench-perf.js，把 stdout/stderr/exit code 全部落盘。
// 之所以存在这个文件：WorkBuddy 的 PowerShell 管道会把子进程 stderr 变成
// 终止错误吞掉，导致任何 stderr 一出现就看不到结果。
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const node = process.execPath;
const r = spawnSync(node, [path.join(__dirname, 'bench-perf.js')], {
  cwd: path.join(__dirname, '..'),
  encoding: 'utf8',
  timeout: 240000
});

const text =
  '=== EXIT ' + r.status + ' (signal ' + (r.signal || 'none') + ') ===\n' +
  '--- error ---\n' + (r.error && (r.error.stack || r.error.message) || '(none)') + '\n' +
  '--- STDOUT ---\n' + (r.stdout || '') + '\n' +
  '--- STDERR ---\n' + (r.stderr || '');
fs.writeFileSync(path.join(__dirname, '_bench_result.txt'), text, 'utf8');
