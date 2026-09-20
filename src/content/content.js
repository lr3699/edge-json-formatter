/**
 * 内容脚本：探测当前页面是否为 JSON，并用查看器接管渲染。
 *
 * 安全约定：
 *  - 只在顶层 frame 运行；
 *  - 只在 document.contentType 为 JSON 类型，或（可选）整段 text/plain 能完整解析为 JSON 时自动接管；
 *  - 查看器挂在 Shadow DOM 中，宿主页面样式不会污染它，它也不会污染宿主页面；
 *  - 提供「还原原文」，随时可完全恢复到浏览器原生渲染。
 */
(function () {
  'use strict';

  var NS = globalThis.__EDGE_JSON_FORMATTER__;
  if (!NS || !NS.createViewer) return;

  // 只处理顶层文档
  try {
    if (window.top !== window) return;
  } catch (e) {
    return;
  }

  var HOST_ID = '__jf_page_host__';
  var HOST_STYLE =
    'all:initial;position:fixed;inset:0;top:0;left:0;right:0;bottom:0;' +
    'width:100%;height:100%;z-index:2147483647;display:block;';

  var settings = Object.assign({}, NS.DEFAULTS);
  var hostEl = null;
  var shadowRoot = null;
  var mountEl = null;
  var viewer = null;
  var savedOverflow = null;
  var busy = false;

  /* ---------------- 探测 ---------------- */

  function contentType() {
    try {
      return String(document.contentType || '').toLowerCase().split(';')[0].trim();
    } catch (e) {
      return '';
    }
  }

  function isJsonContentType() {
    var ct = contentType();
    if (!ct) return false;
    return ct === 'application/json' || ct === 'text/json' ||
      /\+json$/.test(ct) || /^application\/.*json$/.test(ct);
  }

  function isPlainTextContentType() {
    var ct = contentType();
    return ct === 'text/plain' || ct === '';
  }

  /** 取浏览器用于展示原始文本的容器内容 */
  function pageText() {
    if (!document.body) return '';
    var body = document.body;
    var first = body.firstElementChild;
    // 浏览器渲染纯文本响应时是 <body><pre>原文</pre></body>
    if (first && first.tagName === 'PRE' && body.children.length <= 2) {
      return first.textContent || '';
    }
    var pre = body.querySelector('pre');
    if (pre && body.children.length === 1) {
      return pre.textContent || '';
    }
    return body.textContent || '';
  }

  /**
   * 探测当前页面的 JSON 情况。
   * @returns {{ok:boolean, text?:string, lenient?:boolean, reason?:string,
   *            jsonCt?:boolean, broken?:boolean, size?:number}}
   */
  function detect() {
    var jsonCt = isJsonContentType();
    var raw = pageText();
    if (!raw) return { ok: false, jsonCt: jsonCt, reason: '当前页面没有文本内容' };

    var text = raw.replace(/^\uFEFF/, '');
    var trimmed = text.trim();
    if (!trimmed) return { ok: false, jsonCt: jsonCt, reason: '当前页面没有文本内容' };

    var looksLikeJson = trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[';

    // 内容类型不是 JSON，且首字符也不像 JSON → 直接放弃，绝不干扰普通网页
    if (!jsonCt && !looksLikeJson) {
      return { ok: false, jsonCt: false, reason: '当前页面看起来不是 JSON 内容' };
    }

    try {
      NS.parser.parse(trimmed, { lenient: false });
      return { ok: true, jsonCt: jsonCt, text: trimmed, size: trimmed.length };
    } catch (err) {
      try {
        NS.parser.parse(trimmed, { lenient: true });
        return { ok: true, jsonCt: jsonCt, text: trimmed, relaxed: true, size: trimmed.length };
      } catch (err2) {
        // 声明为 JSON 但内容非法：仍然接管，用错误卡片代替浏览器的纯文本视图
        if (jsonCt) {
          return {
            ok: true,
            jsonCt: true,
            broken: true,
            text: trimmed,
            size: trimmed.length
          };
        }
        return { ok: false, jsonCt: false, reason: '当前页面看起来不是 JSON 内容' };
      }
    }
  }

  /* ---------------- 接管渲染 ---------------- */

  function injectSettings(patch) {
    NS.saveSettings(patch);
    broadcastSettings(patch);
  }

  function broadcastSettings(patch) {
    settings = Object.assign({}, settings, patch || {});
    if (viewer) viewer.updateOptions(settings);
  }

  function open(text, options) {
    options = options || {};
    if (hostEl) {
      if (viewer) viewer.setText(text, { lenient: !!options.lenient });
      return;
    }
    savedOverflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = 'hidden';

    hostEl = document.createElement('div');
    hostEl.id = HOST_ID;
    hostEl.setAttribute('style', HOST_STYLE);
    if (options.overlay) {
      hostEl.className = 'jf-overlay-host';
      hostEl.setAttribute('data-jf-overlay', '1');
    }
    shadowRoot = hostEl.attachShadow({ mode: 'open' });

    mountEl = document.createElement('div');
    mountEl.setAttribute('style', 'position:absolute;inset:0;top:0;left:0;right:0;bottom:0;');
    shadowRoot.appendChild(mountEl);

    (document.body || document.documentElement).appendChild(hostEl);

    if (options.overlay) {
      mountEl.remove();
      mountEl = document.createElement('div');
      mountEl.className = 'jf-overlay-panel';
      shadowRoot.appendChild(mountEl);
    }

    viewer = NS.createViewer(mountEl, Object.assign({}, settings, {
      interactive: true,
      overlay: !!options.overlay,
      onRestore: options.overlay ? null : close,
      onClose: options.overlay ? close : null,
      onSettingsChange: injectSettings
    }));
    viewer.setText(text, { lenient: !!options.lenient });
    document.addEventListener('keydown', onKeyDown, true);
  }

  // 工具栏只保留功能按钮，关闭入口统一收敛到 Esc（浮层与整页两种模式都可用）
  function onKeyDown(e) {
    if (e.key === 'Escape' && hostEl) {
      close();
    }
  }

  function close() {
    if (!hostEl) return;
    document.removeEventListener('keydown', onKeyDown, true);
    try {
      if (viewer) viewer.destroy();
    } catch (e) { /* ignore */ }
    if (hostEl.parentNode) hostEl.parentNode.removeChild(hostEl);
    hostEl = null;
    shadowRoot = null;
    mountEl = null;
    viewer = null;
    if (savedOverflow !== null) {
      document.documentElement.style.overflow = savedOverflow;
      savedOverflow = null;
    }
  }

  /* ---------------- 消息通道 ---------------- */

  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (!msg || typeof msg.type !== 'string' || msg.type.indexOf('JF_') !== 0) return;

    switch (msg.type) {
      case 'JF_PING': {
        var d = detect();
        sendResponse({
          ok: true,
          isJson: d.ok,
          formatted: !!hostEl,
          reason: d.ok ? '' : d.reason,
          size: d.size || 0,
          contentType: contentType()
        });
        return true;
      }
      case 'JF_FORMAT': {
        var r = detect();
        if (!r.ok) {
          sendResponse({ ok: false, reason: r.reason });
          return true;
        }
        open(r.text, { overlay: false, lenient: !!r.relaxed });
        sendResponse({ ok: true, lenient: !!r.relaxed, broken: !!r.broken });
        return true;
      }
      case 'JF_FORMAT_TEXT': {
        if (!msg.text) {
          sendResponse({ ok: false, reason: '没有可格式化的文本' });
          return true;
        }
        open(String(msg.text), { overlay: true });
        sendResponse({ ok: true });
        return true;
      }
      case 'JF_RESTORE': {
        close();
        sendResponse({ ok: true });
        return true;
      }
      case 'JF_TOGGLE': {
        if (hostEl) {
          close();
          sendResponse({ ok: true, formatted: false });
        } else {
          var t = detect();
          if (!t.ok) {
            sendResponse({ ok: false, reason: t.reason });
            return true;
          }
          open(t.text, { lenient: !!t.relaxed });
          sendResponse({ ok: true, formatted: true });
        }
        return true;
      }
      case 'JF_SETTINGS_CHANGED': {
        settings = Object.assign({}, NS.DEFAULTS, msg.settings || {});
        if (viewer) viewer.updateOptions(settings);
        sendResponse({ ok: true });
        return true;
      }
      default:
        return;
    }
  });

  /* ---------------- 自动接管 ---------------- */

  function autoRun() {
    if (busy || hostEl) return;
    busy = true;
    NS.loadSettings().then(function (loaded) {
      settings = Object.assign({}, NS.DEFAULTS, loaded);
      if (!settings.autoFormat) return;
      if (!isJsonContentType() && !(settings.autoFormatPlainText && isPlainTextContentType())) return;

      var r = detect();
      if (!r.ok) return;
      if (r.size > settings.maxAutoSize) {
        console.warn('[JSON 格式化] 内容过大（' + r.size + ' 字节），已跳过自动格式化。');
        return;
      }
      open(r.text, { lenient: !!r.relaxed });
    }).catch(function () { /* ignore */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoRun, { once: true });
  } else {
    autoRun();
  }
})();
