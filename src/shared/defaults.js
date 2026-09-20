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
    /** 字号（px）。14~15 是长时间阅读 JSON 的舒适区间，13 及以下在
     *  高分辨率屏上会显得又小又细 */
    fontSize: 15,
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
    maxAutoSize: 20 * 1024 * 1024
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
   * 打开独立编辑页。已经打开过就复用同一个标签页并聚焦，
   * 避免用户点几次就攒出一排重复页面。
   *
   * 为什么不用 tabs.query 找已开的页面：
   *   1) 带 `{url}` 过滤器需要 "tabs" 权限，否则过滤器被静默忽略；
   *   2) 不带过滤器时，没有 "tabs" 权限就读不到 tab.url ——
   *      连本扩展自己的页面也读不到，所以按 URL 比对永远匹配不上。
   * 为了不为一处体验去申请 "tabs" 权限（会多一条权限说明），
   * 改用 runtime.getContexts()：专门用来枚举「哪些标签页里跑着本扩展的页面」，
   * 返回的 documentUrl / tabId / windowId 都不需要额外权限。
   * 该方法自 Chrome/Edge 116 起可用；更老的版本退化为每次都新开一个标签页。
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

    function focusTab(tabId, windowId) {
      chrome.tabs.update(tabId, { active: true }, function () {
        if (chrome.runtime.lastError) return;
        if (windowId !== undefined && windowId >= 0 && chrome.windows) {
          chrome.windows.update(windowId, { focused: true }, function () {
            void chrome.runtime.lastError;
          });
        }
      });
    }

    function create() {
      chrome.tabs.create({ url: url }, function () { void chrome.runtime.lastError; });
    }

    if (typeof chrome.runtime.getContexts !== 'function') {
      create();
      return;
    }

    chrome.runtime.getContexts(
      { contextTypes: ['TAB'], documentUrls: [url] },
      function (contexts) {
        if (chrome.runtime.lastError) { /* 忽略：当作没开过 */ }
        var hit = null;
        for (var i = 0; i < (contexts || []).length; i++) {
          var ctx = contexts[i];
          if (typeof ctx.tabId === 'number' && ctx.tabId >= 0) { hit = ctx; break; }
        }
        if (hit) focusTab(hit.tabId, hit.windowId);
        else create();
      }
    );
  };
})();
