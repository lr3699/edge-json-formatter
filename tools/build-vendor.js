#!/usr/bin/env node
/**
 * build-vendor —— 把 CodeMirror 6 打成自包含 IIFE，落到 src/vendor/codemirror.bundle.js。
 *
 *   node tools/build-vendor.js
 *
 * 产物是**构建产物但要提交**：扩展要过 MV3「无远程代码」审核，运行时不能联网取 JS，
 * 所以 bundle 必须躺在包里。改依赖版本后重跑本脚本即可。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const esbuild = require('esbuild');

const ROOT = path.resolve(__dirname, '..');
const ENTRY = path.join(ROOT, 'src/vendor/cm-entry.js');
const OUT = path.join(ROOT, 'src/vendor/codemirror.bundle.js');
const GLOBAL_NAME = 'JFCodeMirror';

async function main() {
  if (!fs.existsSync(ENTRY)) throw new Error('缺少入口：' + ENTRY);

  const t0 = Date.now();
  const result = await esbuild.build({
    entryPoints: [ENTRY],
    outfile: OUT,
    bundle: true,
    format: 'iife',
    globalName: GLOBAL_NAME,
    platform: 'browser',
    // 扩展的 minimum_chrome_version 是 102；cm6 要求的语法在这个目标下都可用
    target: ['chrome102'],
    minify: true,
    legalComments: 'none',
    charset: 'utf8',
    banner: {
      js: '/* CodeMirror 6 (MIT) 本地打包，禁止改为远程加载 —— MV3 要求。见 tools/build-vendor.js */',
    },
  });

  const size = fs.statSync(OUT).size;
  console.log('打包完成：' + path.relative(ROOT, OUT).replace(/\\/g, '/'));
  console.log('  体积   : ' + (size / 1024).toFixed(1) + ' KB');
  console.log('  耗时   : ' + (Date.now() - t0) + ' ms');
  console.log('  全局名 : ' + GLOBAL_NAME);
  if (result.warnings.length) {
    console.log('  警告   :');
    for (const w of result.warnings) console.log('    - ' + w.text);
  }
}

main().catch((e) => {
  console.error(e && e.message ? e.message : e);
  process.exit(1);
});
