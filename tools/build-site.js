#!/usr/bin/env node
/**
 * build-site.js —— 把扩展的核心模块同步到 site/ ，供网页版（GitHub Pages）使用。
 *
 * 设计原则：不复制粘贴代码，直接从 src/ 取，避免网页版和扩展版逻辑分叉。
 * 只有一处差异需要打补丁：editor.js 是 IIFE，网页版的设置面板要调它内部函数，
 * 所以在拷贝时注入对外钩子（src/ 本身保持原样，不影响已提交审核的包）。
 *
 * 缓存策略（重要）：
 *   GitHub Pages 对所有文件都发 `Cache-Control: max-age=600`，文件名不变就会被
 *   浏览器直接用缓存——改完代码刷新还是旧的。所以产物不写固定路径，而是写进
 *   `assets/<构建号>/`，并同步改写 HTML 里的引用：
 *     - 构建号 = 所有产物 + 站点自有资源内容一起算的 sha256 前 8 位（确定性：
 *       源码没变 → 构建号不变 → 仓库不产生无意义改动；源码一变 → 目录换名 →
 *       浏览器必然重新下载，没有任何缓存残留）。
 *     - 站点自有资源（web-storage.js / web-settings.js / style.css / app.css /
 *       favicon.png / og-image.png）不搬进构建目录，改成加 `?v=<构建号>` 查询串。
 *     - 每次构建清理 site/assets/ 下其它构建目录，仓库不会越堆越乱。
 *
 * 用法：node tools/build-site.js
 */

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'src');
const SITE = path.join(ROOT, 'site');
const ASSETS = path.join(SITE, 'assets');

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

/** 从 src/ 生成、每次构建都会重写的产物 */
const FILES = [
  ['shared/defaults.js', 'defaults.js'],
  ['content/json-parser.js', 'json-parser.js'],
  ['content/viewer.js', 'viewer.js'],
  ['editor/editor.js', 'editor.js'],
  ['editor/editor.css', 'editor.css']
];

/** 站点自有、不进构建目录，只加 ?v= 查询串的资源 */
const STATIC_ASSETS = ['web-storage.js', 'web-settings.js', 'style.css', 'app.css',
                       'favicon.png', 'og-image.png'];

const BUILD_DIR_RE = /^[0-9a-f]{8}$/;

function hash8(parts) {
  const h = crypto.createHash('sha256');
  parts.forEach(function (p) { h.update(p); h.update('\u0000'); });
  return h.digest('hex').slice(0, 8);
}

function readIfExists(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch (e) { return null; }
}

/** 生成产物内容（含 editor.js 的网页版钩子注入） */
function buildContents() {
  const out = {};
  FILES.forEach(function (pair) {
    let src = fs.readFileSync(path.join(SRC, pair[0]), 'utf8');
    if (pair[1] === 'editor.js') {
      const idx = src.lastIndexOf('})();');
      if (idx === -1) throw new Error('editor.js 里找不到 IIFE 结尾 })();');
      src = src.slice(0, idx) + HOOKS + '\n' + src.slice(idx);
    }
    out[pair[1]] = src;
  });
  return out;
}

/** 构建号：产物 + 站点自有资源一起参与，任何一项变了目录名就变 */
function computeBuildId(out) {
  const parts = [];
  FILES.forEach(function (pair) { parts.push(pair[1] + ':' + out[pair[1]]); });
  STATIC_ASSETS.forEach(function (name) {
    const buf = readIfExists(path.join(ASSETS, name)) || readIfExists(path.join(SITE, name));
    if (buf !== null) parts.push(name + ':' + buf);
  });
  return hash8(parts);
}

/** 清理旧构建目录与上一代扁平产物 */
function cleanStale(buildId) {
  const removed = [];
  let entries = [];
  try { entries = fs.readdirSync(ASSETS, { withFileTypes: true }); } catch (e) { return removed; }
  const builtNames = FILES.map(function (p) { return p[1]; });
  entries.forEach(function (e) {
    if (e.isDirectory()) {
      if (BUILD_DIR_RE.test(e.name) && e.name !== buildId) {
        fs.rmSync(path.join(ASSETS, e.name), { recursive: true, force: true });
        removed.push(e.name + '/');
      }
      return;
    }
    // 老布局（assets/editor.js 这种扁平产物）一并清掉，免得留着误导
    if (builtNames.indexOf(e.name) !== -1) {
      fs.unlinkSync(path.join(ASSETS, e.name));
      removed.push(e.name);
    }
  });
  return removed;
}

/**
 * 改写 HTML 里的本地资源引用：
 *   assets/<旧构建号>/foo.js  → assets/<新构建号>/foo.js
 *   style.css                 → style.css?v=<构建号>
 * 外部链接（http/https/mailto/锚点/data:）一律不动。
 */
function rewriteHtml(html, buildId, builtNames) {
  // 先把上一次的构建目录前缀脱掉，保证重复构建幂等
  html = html.replace(/assets\/[0-9a-f]{8}\//g, 'assets/');

  const RE = /(href|src|content)="((?!https?:|mailto:|#|data:)[^"]+?\.(?:css|js|png))(?:\?v=[0-9a-f]+)?"/g;
  return html.replace(RE, function (whole, attr, url) {
    const base = url.split('/').pop();
    if (url.indexOf('assets/') === 0 && builtNames.indexOf(base) !== -1) {
      return attr + '="assets/' + buildId + '/' + base + '"';
    }
    return attr + '="' + url + '?v=' + buildId + '"';
  });
}

function main() {
  fs.mkdirSync(ASSETS, { recursive: true });

  const out = buildContents();
  const buildId = computeBuildId(out);
  const dir = path.join(ASSETS, buildId);
  fs.mkdirSync(dir, { recursive: true });

  console.log('构建号 ' + buildId + '  →  site/assets/' + buildId + '/');
  FILES.forEach(function (pair) {
    const content = out[pair[1]];
    fs.writeFileSync(path.join(dir, pair[1]), content);
    console.log('  assets/' + buildId + '/' + pair[1].padEnd(16) + content.length + ' bytes');
  });

  const builtNames = FILES.map(function (p) { return p[1]; });
  const removed = cleanStale(buildId);
  if (removed.length) console.log('  清理旧产物：' + removed.join(', '));

  console.log('\n改写 HTML 引用：');
  fs.readdirSync(SITE).filter(function (f) { return /\.html$/.test(f); }).forEach(function (f) {
    const p = path.join(SITE, f);
    const before = fs.readFileSync(p, 'utf8');
    const after = rewriteHtml(before, buildId, builtNames);
    if (after !== before) fs.writeFileSync(p, after);
    console.log('  ' + f.padEnd(14) + (after !== before ? '已更新' : '无变化'));
  });

  console.log('\n完成：site/ 已与 src/ 同步；资源路径带构建号，浏览器不会再吃到旧缓存');
}

main();
