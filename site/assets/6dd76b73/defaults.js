/**
 * 共享的默认配置。
 * 被 content script（隔离环境）与 popup / options / service worker 各自加载一份。
 */
(function () {
  'use strict';

  var NS = (globalThis.__EDGE_JSON_FORMATTER__ =
    globalThis.__EDGE_JSON_FORMATTER__ || {});

  NS.DEFAULTS = {
    /** 打开 JSON 页面时自动格式化 */
    autoFormat: true,
    /** 对 text/plain 但整段内容可解析为 JSON 的页面也自动格式化 */
    autoFormatPlainText: true,
    /** 字符串默认保留源码中的转义写法（\n、\uXXXX 原样显示） */
    keepEscape: true,
    /** 缩进宽度：2 / 4 / 'tab' */
    indent: 2,
    /** 主题：auto | light | dark */
    theme: 'auto',
    /** 自动展开层级 */
    expandDepth: 2,
    /** 字号（px）。14 是「不显大、又够清晰」的平衡点：15 以上中文虽然更大，
     *  但在 125% 缩放的屏幕上会挤掉一屏能看的行数；13 及以下中文笔画会挤在
     *  一起、反而更难认。中文由字体栈里的雅黑/PingFang 渲染（见 viewer.js）。 */
    fontSize: 14,
    /** 显示行号 */
    lineNumbers: false,
    /** 对象键按字母排序 */
    sortKeys: false,
    /** 使用等宽字体 */
    monoFont: true,
    /** 右键菜单 */
    contextMenu: true,
    /** 单个 JSON 体积上限（字节），超过则只提示不自动渲染。
     *  20MB：编辑页大输入已绕过 textarea 直接进查看器（查看器分批渲染、
     *  有行数上限），20MB 内都能流畅自动格式化；超过才提示 Ctrl+Enter 强制。 */
    maxAutoSize: 20 * 1024 * 1024,
    /** JSON 缩进宽度（大文档视图与导出共用） */
    indent: 2,
    /** 长行自动换行（大文档视图） */
    wrap: false
  };

  NS.STORAGE_KEY = 'jsonFormatterSettings';

  /** 读取设置（带默认值兜底） */
  NS.loadSettings = function loadSettings() {
    return new Promise(function (resolve) {
      try {
        chrome.storage.sync.get(NS.DEFAULTS, function (items) {
          if (chrome.runtime.lastError) {
            chrome.storage.local.get(NS.DEFAULTS, function (local) {
              resolve(Object.assign({}, NS.DEFAULTS, local || {}));
            });
            return;
          }
          resolve(Object.assign({}, NS.DEFAULTS, items || {}));
        });
      } catch (e) {
        resolve(Object.assign({}, NS.DEFAULTS));
      }
    });
  };

  /** 保存设置 */
  NS.saveSettings = function saveSettings(patch) {
    return new Promise(function (resolve) {
      try {
        chrome.storage.sync.set(patch, function () {
          if (chrome.runtime.lastError) {
            chrome.storage.local.set(patch, function () {
              resolve();
            });
            return;
          }
          resolve();
        });
      } catch (e) {
        resolve();
      }
    });
  };

  /** 缩进字符串 */
  NS.indentUnit = function indentUnit(indent) {
    if (indent === 'tab' || indent === 'Tab') return '\t';
    var n = parseInt(indent, 10);
    if (!n || n < 0) n = 2;
    return new Array(n + 1).join(' ');
  };

  /** 独立编辑页（粘贴 JSON 格式化）在扩展内的路径 */
  NS.EDITOR_PAGE = 'src/editor/editor.html';

  /**
   * 打开独立编辑页。
   *
   * 行为约定：**每次点击工具栏图标都重新打开一个全新的编辑页标签**，
   * 不复用、不聚焦已有的编辑页。这样用户点几次就能并排多个独立编辑实例，
   * 互不覆盖上次的内容。
   *
   * 只在有 chrome.tabs 的环境（popup / options / service worker）里可用；
   * content script 注入的页面里调用会静默返回，不会抛错。
   */
  NS.openEditor = function openEditor() {
    if (typeof chrome === 'undefined' || !chrome.tabs || !chrome.runtime ||
        !chrome.runtime.getURL || !chrome.runtime.id) {
      return;
    }
    var url = chrome.runtime.getURL(NS.EDITOR_PAGE);
    chrome.tabs.create({ url: url }, function () { void chrome.runtime.lastError; });
  };
})();
