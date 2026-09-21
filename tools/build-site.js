#!/usr/bin/env node
/**
 * build-site.js —— 把扩展的核心模块同步到 site/ ，供网页版（GitHub Pages）使用。
 *
 * 设计原则：不复制粘贴代码，直接从 src/ 取，避免网页版和扩展版逻辑分叉。
 * 只有一处差异需要打补丁：editor.js 是 IIFE，网页版的设置面板要调它内部函数，
 * 所以在拷贝时注入三个对外钩子（src/ 本身保持原样，不影响已提交审核的包）。
 *
 * 用法：node tools/build-site.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'src');
const ASSETS = path.join(ROOT, 'site', 'assets');

/** 注入到 editor.js 末尾（IIFE 内部）的网页版钩子 */
const HOOKS = [
  '',
  '  /* ---- 网页版钩子（由 tools/build-site.js 注入，src/ 里没有） ---- */',
  '  NS.getEditorSettings = function () {',
  '    return Object.assign({}, settings);',
  '  };',
  '',
  '  /** 设置面板改一项 → 立即生效 + 落盘 + 同步整页主题 */',
  '  NS.applyEditorSettings = function (patch) {',
  '    Object.assign(settings, patch);',
  '    NS.saveSettings(patch);',
  '    applySettingsToViewer();',
  '    var t = settings.theme;',
  '    if (t === "auto") {',
  '      t = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches',
  '        ? "dark" : "light";',
  '    }',
  '    applyPageTheme(t);',
  '  };',
  '',
  '  /** 从外部灌入一段文本并立即格式化（URL 加载 / 分享链接用） */',
  '  NS.setEditorText = function (text) {',
  '    setInputText(text);',
  '    inputKind = "drop";',
  '    formatNow();',
  '  };',
  '',
  '  /** 读取当前输入源文本（大文本模式下 textarea 被隐藏，必须走这里） */',
  '  NS.getEditorText = function () {',
  '    return sourceText;',
  '  };',
  ''
].join('\n');

const FILES = [
  ['shared/defaults.js', 'defaults.js'],
  ['content/json-parser.js', 'json-parser.js'],
  ['content/viewer.js', 'viewer.js'],
  ['editor/editor.js', 'editor.js'],
  ['editor/editor.css', 'editor.css']
];

function main() {
  fs.mkdirSync(ASSETS, { recursive: true });

  FILES.forEach(function (pair) {
    const from = path.join(SRC, pair[0]);
    const to = path.join(ASSETS, pair[1]);
    let src = fs.readFileSync(from, 'utf8');

    if (pair[1] === 'editor.js') {
      if (src.indexOf('NS.applyEditorSettings') !== -1) {
        // 已经打过补丁：先还原成干净副本再打，避免重复注入
        src = fs.readFileSync(from, 'utf8');
      }
      const idx = src.lastIndexOf('})();');
      if (idx === -1) throw new Error('editor.js 里找不到 IIFE 结尾 })();');
      src = src.slice(0, idx) + HOOKS + '\n' + src.slice(idx);
    }

    fs.writeFileSync(to, src);
    console.log('  assets/' + pair[1].padEnd(16) + src.length + ' bytes');
  });

  console.log('\n完成：site/assets/ 已与 src/ 同步');
}

main();
