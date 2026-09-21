/**
 * web-settings.js —— 网页版专属的「设置抽屉」+ 从 URL 加载 + 分享链接。
 *
 * 扩展里这些能力由 options 页和右键菜单提供；网页版没有扩展环境，
 * 所以在这里补齐一份等价入口。设置改完直接走 NS.applyEditorSettings，
 * 与查看器共用同一份状态并写入 localStorage。
 */
(function () {
  'use strict';

  var NS = globalThis.__EDGE_JSON_FORMATTER__;
  if (!NS || !NS.applyEditorSettings) return;

  var $ = function (id) { return document.getElementById(id); };

  /** 控件定义：key 对应 NS.DEFAULTS 的字段 */
  var FIELDS = [
    {
      key: 'theme', label: '主题', type: 'select',
      options: [['auto', '跟随系统'], ['light', '浅色'], ['dark', '深色']]
    },
    {
      key: 'indent', label: '缩进', type: 'select',
      options: [[2, '2 空格'], [4, '4 空格'], ['tab', 'Tab']]
    },
    {
      key: 'fontSize', label: '字号', type: 'select', cast: 'number',
      options: [[13, '13px'], [14, '14px'], [15, '15px'], [16, '16px'], [17, '17px'], [18, '18px']]
    },
    {
      key: 'expandDepth', label: '默认展开', type: 'select', cast: 'number',
      options: [[1, '第 1 层'], [2, '第 2 层'], [3, '第 3 层'], [4, '第 4 层'], [99, '全部展开']]
    },
    { key: 'keepEscape', label: '保留转义写法（\\n、\\uXXXX 原样显示）', type: 'check' },
    { key: 'lineNumbers', label: '显示行号', type: 'check' },
    { key: 'sortKeys', label: '对象键按字母排序', type: 'check' },
    { key: 'monoFont', label: '使用等宽字体', type: 'check' }
  ];

  var drawer = $('drawer');
  var mask = $('drawerMask');
  var body = $('drawerBody');

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function castValue(field, raw) {
    if (field.cast === 'number') return parseInt(raw, 10);
    return raw;
  }

  /* ---------------- 抽屉开关 ---------------- */

  function openDrawer() {
    drawer.hidden = false;
    mask.hidden = false;
    document.body.classList.add('drawer-open');
  }

  function closeDrawer() {
    drawer.hidden = true;
    mask.hidden = true;
    document.body.classList.remove('drawer-open');
  }

  /* ---------------- 构建控件 ---------------- */

  function buildControls(settings) {
    body.textContent = '';

    FIELDS.forEach(function (field) {
      var row = el('div', 'set-row');
      row.appendChild(el('label', 'set-label', field.label));

      if (field.type === 'select') {
        var sel = el('select', 'set-select');
        field.options.forEach(function (opt) {
          var o = el('option', null, opt[1]);
          o.value = String(opt[0]);
          sel.appendChild(o);
        });
        sel.value = String(settings[field.key]);
        sel.addEventListener('change', function () {
          var patch = {};
          patch[field.key] = castValue(field, sel.value);
          NS.applyEditorSettings(patch);
        });
        row.appendChild(sel);
      } else {
        var wrap = el('label', 'set-switch');
        var cb = el('input');
        cb.type = 'checkbox';
        cb.checked = !!settings[field.key];
        cb.addEventListener('change', function () {
          var patch = {};
          patch[field.key] = cb.checked;
          NS.applyEditorSettings(patch);
        });
        wrap.appendChild(cb);
        wrap.appendChild(el('span', 'set-switch-track'));
        row.appendChild(wrap);
      }

      body.appendChild(row);
    });
  }

  /* ---------------- 从 URL 加载 ---------------- */

  function setMsg(text, kind) {
    var msg = $('msg');
    if (!msg) return;
    msg.textContent = text || '';
    msg.className = 'msg' + (kind ? ' ' + kind : '');
  }

  var MAX_SHARE = 200000;

  function loadFromUrl() {
    var input = $('urlInput');
    var url = (input.value || '').trim();
    if (!url) { setMsg('先填一个 URL', 'err'); return; }
    if (!/^https?:\/\//i.test(url)) url = 'https://' + url;

    setMsg('正在获取…');
    fetch(url, { mode: 'cors', credentials: 'omit' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
      })
      .then(function (text) {
        NS.setEditorText(text);
        setMsg('已载入 ' + url.replace(/^https?:\/\//i, '').slice(0, 60), 'ok');
        closeDrawer();
      })
      .catch(function (err) {
        setMsg('取不到：' + (err && err.message ? err.message : '未知错误') +
               '。多数接口不允许跨域访问（CORS），这种情况请直接粘贴文本。', 'err');
      });
  }

  /* ---------------- 分享链接 ---------------- */

  function currentText() {
    var ta = $('input');
    return ta && !ta.hidden ? ta.value : '';
  }

  function shareLink() {
    var text = currentText();
    if (!text) { setMsg('左边还没有内容', 'err'); return; }
    if (text.length > MAX_SHARE) {
      setMsg('内容超过 ' + Math.round(MAX_SHARE / 1000) + ' KB，链接塞不下，用「下载」导出吧', 'err');
      return;
    }
    var url = location.origin + location.pathname +
              '#j=' + encodeURIComponent(text);
    history.replaceState(null, '', '#j=' + encodeURIComponent(text));

    var done = function () { setMsg('链接已复制到剪贴板，打开即还原这段 JSON', 'ok'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, function () {
        setMsg('链接已写入地址栏，请手动复制', 'ok');
      });
    } else {
      setMsg('链接已写入地址栏，请手动复制', 'ok');
    }
  }

  /* ---------------- 启动 ---------------- */

  NS.loadSettings().then(function (settings) {
    buildControls(settings);

    // 设置按钮在 editor.js 里因「不在扩展环境」被隐藏，这里接管它
    var btn = $('btnOptions');
    if (btn) {
      btn.hidden = false;
      btn.addEventListener('click', openDrawer);
    }
    if ($('drawerClose')) $('drawerClose').addEventListener('click', closeDrawer);
    if (mask) mask.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !drawer.hidden) closeDrawer();
    });

    if ($('btnUrlGo')) $('btnUrlGo').addEventListener('click', loadFromUrl);
    if ($('urlInput')) {
      $('urlInput').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); loadFromUrl(); }
      });
    }
    if ($('btnShare')) $('btnShare').addEventListener('click', shareLink);

    // 带 #j= 的分享链接：打开时直接还原
    var m = /^#j=(.*)$/.exec(location.hash || '');
    if (m && m[1]) {
      try {
        var text = decodeURIComponent(m[1]);
        if (text) NS.setEditorText(text);
      } catch (e) { /* hash 不是合法编码就忽略 */ }
    }
  });
})();
