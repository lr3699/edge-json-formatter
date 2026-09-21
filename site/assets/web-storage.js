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

  // 扩展里用于「打开独立编辑页」，网页版不存在这个概念
  NS.openEditor = function openEditor() { /* no-op */ };
})();
