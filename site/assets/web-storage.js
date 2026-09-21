/**
 * web-storage.js —— 网页版专属：把设置存储从 chrome.storage 换成 localStorage。
 *
 * 必须在 defaults.js 之后、editor.js 之前加载：
 * defaults.js 里的 loadSettings / saveSettings 走的是扩展的 chrome.storage，
 * 普通网页里没有，这里整体覆盖掉；其余（DEFAULTS / indentUnit）原样保留，
 * 保证网页版与扩展版共用同一套默认值。
 */
(function () {
  'use strict';

  var NS = globalThis.__EDGE_JSON_FORMATTER__;
  if (!NS) return;

  var KEY = NS.STORAGE_KEY || 'jsonFormatterSettings';

  function readAll() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || '{}') || {};
    } catch (e) {
      return {};
    }
  }

  NS.loadSettings = function loadSettings() {
    return Promise.resolve(Object.assign({}, NS.DEFAULTS, readAll()));
  };

  NS.saveSettings = function saveSettings(patch) {
    try {
      localStorage.setItem(KEY, JSON.stringify(Object.assign(readAll(), patch)));
    } catch (e) { /* 隐私模式下 localStorage 不可写：忽略，功能不受影响 */ }
    return Promise.resolve();
  };

  /**
   * 一次性迁移（uiVersion）。
   * 这一版把默认字号从 15 调成了 14（15 在 125% 缩放的屏上偏大，还挤掉可读行数）。
   * 老访客的 localStorage 里存着 15——那是「旧的默认值」，不迁移的话改默认也白改。
   * 只在「存的正好是旧默认 15」且没有迁移标记时才抹掉，用户手动选过的其它值不动。
   */
  var UI_VERSION = 2;
  (function migrate() {
    var all = readAll();
    if (all.uiVersion === UI_VERSION) return;
    if (all.fontSize === 15) delete all.fontSize;
    if (all.lineNumbers === false) delete all.lineNumbers; // 行号默认关闭 → 交回默认
    all.uiVersion = UI_VERSION;
    try { localStorage.setItem(KEY, JSON.stringify(all)); } catch (e) { /* 同上 */ }
  })();

  // 扩展里用于「打开独立编辑页」，网页版不存在这个概念
  NS.openEditor = function openEditor() { /* no-op */ };
})();
