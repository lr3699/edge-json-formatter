/**
 * JSON 查看器：语法高亮 + 可折叠树 + 搜索 + 路径复制 + 转义保留/还原 + 主题。
 *
 * 视觉规格取自参考设计稿的实测取色：
 *   键名 #92278F（紫）  字符串 #3AB54A（绿）  数字 #20A8E0（浅蓝）
 *   布尔 #E85050（珊瑚红）  折叠标记为键与括号之间的珊瑚红圆角方框
 *
 * 本模块不依赖任何 chrome.* API，可直接在普通网页中复用（见 preview/demo.html）。
 * 样式注入到挂载点的根节点（ShadowRoot 或 document.head），配合 .jf-root 的
 * `all: initial` 实现与宿主页面的双向隔离。
 */
(function () {
  'use strict';

  var NS = (globalThis.__EDGE_JSON_FORMATTER__ =
    globalThis.__EDGE_JSON_FORMATTER__ || {});

  var SVG_NS = 'http://www.w3.org/2000/svg';

  /* ------------------------------------------------------------------ *
   * 设计变量
   * ------------------------------------------------------------------ */
  var INDENT_PX = 16;   // 每层缩进，与 CSS 里的 --jf-indent 保持一致

  /**
   * 字体栈。
   * 把 Windows 自带的 Cascadia Mono / Consolas 提到最前：这两个字形比
   * `ui-monospace` 兜底命中的字体饱满，13~15px 下不会显得笔画很「瘦」。
   */
  var MONO_FONT = '"Cascadia Mono",Consolas,ui-monospace,SFMono-Regular,"SF Mono",' +
                  'Menlo,"Liberation Mono","Courier New",monospace';
  /** 取消「等宽字体」时使用：同字号下观感更大、笔画更实 */
  var PROSE_FONT = 'system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif';

  /** 正文字号兜底值（px），与 defaults.js 的 fontSize 保持一致 */
  var DEFAULT_FONT_SIZE = 15;

  /* ------------------------------------------------------------------ *
   * 样式
   * ------------------------------------------------------------------ */
  var VIEWER_CSS = [
    '.jf-root{all:initial;}',
    '.jf-root{',
    '  --jf-indent:' + INDENT_PX + 'px;',
    '  --jf-bg:#ffffff;',
    '  --jf-bg-alt:#fafafa;',
    '  --jf-bg-hover:#f2f6fb;',
    '  --jf-border:#e8e8e8;',
    '  --jf-border-strong:#dcdcdc;',
    '  --jf-text:#333333;',
    '  --jf-muted:#9aa0a6;',
    '  --jf-key:#92278f;',
    '  --jf-str:#3ab54a;',
    '  --jf-num:#20a8e0;',
    '  --jf-bool:#e85050;',
    '  --jf-null:#a0a4a8;',
    '  --jf-punct:#b7bcc2;',
    '  --jf-toggle:#e85050;',
    '  --jf-toggle-hover:#c93b3b;',
    '  --jf-guide:#eef0f3;',
    '  --jf-accent:#20a8e0;',
    '  --jf-accent-soft:#e8f5fd;',
    '  --jf-ok:#3ab54a;',
    '  --jf-ok-soft:#eaf7ec;',
    '  --jf-primary:#3ab54a;',
    '  --jf-primary-hover:#2f9e3d;',
    '  --jf-key-bg:rgba(146,39,143,.08);',
    '  --jf-mark:#fff2a8;',
    '  --jf-mark-cur:#ffd84d;',
    '  --jf-shadow:0 12px 48px rgba(15,23,42,.18);',
    '  position:relative;display:flex;flex-direction:column;height:100%;width:100%;',
    '  background:var(--jf-bg);color:var(--jf-text);',
    '  font-family:' + MONO_FONT + ';',
    '  font-size:' + DEFAULT_FONT_SIZE + 'px;line-height:1.7;letter-spacing:normal;text-align:left;',
    '  direction:ltr;font-weight:500;font-style:normal;text-transform:none;',
    '  visibility:visible;opacity:1;overflow:hidden;',
    '}',
    '.jf-root[data-theme="dark"]{',
    '  --jf-bg:#15171c;--jf-bg-alt:#1b1e24;--jf-bg-hover:#22262e;',
    '  --jf-border:#2b3038;--jf-border-strong:#363c46;',
    '  --jf-text:#d7dbe0;--jf-muted:#6f7681;',
    '  --jf-key:#c98ad4;--jf-str:#79d17f;--jf-num:#4dc4f0;--jf-bool:#ff8a8a;',
    '  --jf-null:#7d8590;--jf-punct:#5b626c;--jf-toggle:#ff8a8a;--jf-toggle-hover:#ffb0b0;',
    '  --jf-guide:#242830;--jf-accent:#4dc4f0;--jf-accent-soft:#12303d;',
    '  --jf-ok:#79d17f;--jf-ok-soft:#16301a;',
    '  --jf-primary:#2f9e3d;--jf-primary-hover:#3ab54a;',
    '  --jf-key-bg:rgba(201,138,212,.14);',
    '  --jf-mark:#5c4b1a;--jf-mark-cur:#8a6d1f;',
    '  --jf-shadow:0 12px 48px rgba(0,0,0,.55);',
    '}',
    '.jf-root *,.jf-root *::before,.jf-root *::after{box-sizing:border-box;}',

    /* ---------------- 工具栏 ---------------- */
    '.jf-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:4px;padding:8px 12px;',
    '  border-bottom:1px solid var(--jf-border);background:var(--jf-bg-alt);flex:0 0 auto;}',
    '.jf-sep{width:1px;height:20px;background:var(--jf-border-strong);margin:0 6px;flex:0 0 auto;}',
    '.jf-spacer{flex:1 1 auto;min-width:8px;}',

    '.jf-btn{display:inline-flex;align-items:center;justify-content:center;gap:5px;',
    '  height:30px;min-width:30px;padding:0 8px;border:1px solid transparent;border-radius:7px;',
    '  background:transparent;color:var(--jf-text);font:inherit;font-size:12.5px;line-height:1;',
    '  cursor:pointer;white-space:nowrap;transition:background .14s,color .14s,border-color .14s;}',
    '.jf-btn:hover:not([disabled]){background:var(--jf-accent-soft);color:var(--jf-accent);}',
    '.jf-btn:active:not([disabled]){transform:translateY(1px);}',
    '.jf-btn[disabled]{opacity:.4;cursor:not-allowed;}',
    '.jf-btn svg{width:16px;height:16px;flex:0 0 auto;display:block;}',
    '.jf-btn-icon{width:30px;padding:0;}',
    '.jf-btn-primary{background:var(--jf-primary);border-color:var(--jf-primary);color:#fff;',
    '  font-weight:600;padding:0 14px;}',
    '.jf-btn-primary:hover:not([disabled]){background:var(--jf-primary-hover);',
    '  border-color:var(--jf-primary-hover);color:#fff;}',
    '.jf-btn-outline{border-color:var(--jf-primary);color:var(--jf-primary);background:transparent;',
    '  font-weight:600;padding:0 14px;}',
    '.jf-btn-outline:hover:not([disabled]){background:var(--jf-ok-soft);',
    '  border-color:var(--jf-primary);color:var(--jf-primary);}',

    '.jf-field{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--jf-muted);',
    '  padding-left:6px;}',
    '.jf-select{height:30px;padding:0 26px 0 9px;border:1px solid transparent;border-radius:7px;',
    '  background:transparent;color:var(--jf-text);font:inherit;font-size:12.5px;cursor:pointer;',
    '  outline:none;appearance:none;-webkit-appearance:none;',
    '  background-image:url("data:image/svg+xml;charset=utf8,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'%239aa0a6\' stroke-width=\'2.4\' stroke-linecap=\'round\' stroke-linejoin=\'round\'%3E%3Cpath d=\'m6 9 6 6 6-6\'/%3E%3C/svg%3E");',
    '  background-repeat:no-repeat;background-position:right 7px center;background-size:12px;}',
    '.jf-select:hover{background-color:var(--jf-accent-soft);color:var(--jf-accent);}',
    '.jf-select:focus{border-color:var(--jf-accent);}',
    '.jf-select option{background:var(--jf-bg);color:var(--jf-text);}',

    '.jf-search{position:relative;display:inline-flex;align-items:center;}',
    '.jf-search input{height:30px;width:180px;padding:0 10px 0 30px;border:1px solid transparent;',
    '  border-radius:7px;background:var(--jf-bg);color:var(--jf-text);font:inherit;font-size:12.5px;',
    '  outline:none;transition:border-color .14s,width .18s;}',
    '.jf-search input::placeholder{color:var(--jf-muted);}',
    '.jf-search input:focus{border-color:var(--jf-accent);width:220px;}',
    '.jf-search .jf-search-icon{position:absolute;left:9px;width:14px;height:14px;',
    '  color:var(--jf-muted);pointer-events:none;}',
    '.jf-hits{font-size:11.5px;color:var(--jf-muted);min-width:46px;text-align:center;white-space:nowrap;}',

    '.jf-check{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 10px;',
    '  border-radius:7px;font-size:12.5px;cursor:pointer;user-select:none;color:var(--jf-text);}',
    '.jf-check:hover{background:var(--jf-accent-soft);}',
    '.jf-check input{width:15px;height:15px;margin:0;accent-color:#3ab54a;cursor:pointer;}',

    /* ---------------- 正文 ---------------- */
    '.jf-body{flex:1 1 auto;overflow:auto;padding:14px 18px 80px;background:var(--jf-bg);}',
    '.jf-body::-webkit-scrollbar{width:13px;height:13px;}',
    '.jf-body::-webkit-scrollbar-thumb{background:#d4d8dd;border:3px solid var(--jf-bg);border-radius:8px;}',
    '.jf-body::-webkit-scrollbar-thumb:hover{background:#bcc2c9;}',
    '.jf-root[data-theme="dark"] .jf-body::-webkit-scrollbar-thumb{background:#39404a;}',

    '.jf-row{display:flex;align-items:flex-start;white-space:pre-wrap;word-break:break-word;',
    '  border-radius:4px;padding:0 3px;}',
    '.jf-row:hover{background:var(--jf-bg-hover);}',
    '.jf-no{flex:0 0 auto;width:4em;padding-right:1.1em;text-align:right;color:var(--jf-muted);',
    '  opacity:.55;user-select:none;font-size:.86em;line-height:2.03;background:var(--jf-bg);',
    '  margin-left:calc(var(--jf-indent) * var(--jf-depth,0) * -1);}',
    '.jf-content{flex:1 1 auto;min-width:0;}',

    /* 折叠子层：用嵌套容器 + 左侧引导线表达层级 */
    '.jf-children{padding-left:var(--jf-indent);border-left:1px solid var(--jf-guide);',
    '  margin-left:2px;}',
    '.jf-children-collapsed{display:none;}',

    /* 键与括号之间的圆角方框折叠标记 */
    '.jf-toggle{display:inline-flex;align-items:center;justify-content:center;',
    '  width:15px;height:15px;margin:0 3px;padding:0;border:0;background:none;',
    '  color:var(--jf-toggle);cursor:pointer;vertical-align:-2.5px;}',
    '.jf-toggle svg{width:14px;height:14px;display:block;pointer-events:none;}',
    '.jf-toggle:hover{color:var(--jf-toggle-hover);}',

    '.jf-key{color:var(--jf-key);font-weight:600;cursor:pointer;border-radius:3px;}',
    '.jf-key:hover{background:var(--jf-key-bg,rgba(146,39,143,.09));}',
    '.jf-str{color:var(--jf-str);}',
    '.jf-num{color:var(--jf-num);}',
    '.jf-bool{color:var(--jf-bool);}',
    '.jf-null{color:var(--jf-null);font-style:italic;}',
    '.jf-punct{color:var(--jf-punct);}',
    '.jf-summary{color:var(--jf-muted);font-style:italic;font-size:.92em;cursor:pointer;}',
    '.jf-summary:hover{color:var(--jf-accent);}',
    '.jf-mark{background:var(--jf-mark);border-radius:2px;color:inherit;}',
    '.jf-mark-cur{background:var(--jf-mark-cur);border-radius:2px;}',
    '.jf-flash{animation:jf-flash 1.1s ease-out;}',
    '@keyframes jf-flash{0%{background:var(--jf-mark-cur);}100%{background:transparent;}}',

    /* ---------------- 状态栏 ---------------- */
    '.jf-status{flex:0 0 auto;display:flex;align-items:center;gap:12px;padding:6px 24px 6px 14px;',
    '  border-top:1px solid var(--jf-border);background:var(--jf-bg-alt);',
    '  font-size:11.5px;color:var(--jf-muted);overflow:hidden;}',
    '.jf-status > span:last-child{flex:0 0 auto;white-space:nowrap;}',
    '.jf-path{flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;}',
    '.jf-path:hover{color:var(--jf-accent);}',
    '.jf-path b{color:var(--jf-key);font-weight:600;}',

    /* ---------------- 提示 ---------------- */
    '.jf-toast{position:absolute;left:50%;bottom:52px;transform:translateX(-50%) translateY(8px);',
    '  background:#2b2f36;color:#fff;padding:8px 16px;border-radius:8px;font-size:12.5px;',
    '  opacity:0;pointer-events:none;transition:opacity .18s,transform .18s;z-index:5;',
    '  max-width:80%;box-shadow:0 6px 24px rgba(0,0,0,.18);}',
    '.jf-root[data-theme="dark"] .jf-toast{background:#e6edf3;color:#15171c;}',
    '.jf-toast-show{opacity:1;transform:translateX(-50%) translateY(0);}',

    /* ---------------- 错误卡片 ---------------- */
    '.jf-error{margin:16px 0;padding:18px 20px;border:1px solid var(--jf-border);',
    '  border-left:3px solid #e85050;border-radius:10px;background:var(--jf-bg-alt);max-width:860px;',
    '  font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}',
    '.jf-error h3{margin:0 0 10px;font-size:14px;color:#e85050;font-weight:700;}',
    '.jf-error p{margin:0 0 10px;font-size:13px;color:var(--jf-text);line-height:1.7;}',
    '.jf-error pre{margin:0 0 10px;padding:12px 14px;background:var(--jf-bg);',
    '  border:1px solid var(--jf-border);border-radius:8px;overflow:auto;font-size:12.5px;',
    '  line-height:1.7;color:var(--jf-text);}',
    '.jf-error .jf-caret{color:#e85050;font-weight:700;}',
    '.jf-error .jf-meta{color:var(--jf-muted);font-size:12px;margin:0 0 12px;}',
    '.jf-empty{padding:32px;color:var(--jf-muted);text-align:center;}',

    /* ---------------- 覆盖层 ---------------- */
    '.jf-overlay-host{background:rgba(15,23,42,.45);}',
    '.jf-overlay-panel{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);',
    '  width:min(1080px,93vw);height:min(780px,88vh);border-radius:12px;overflow:hidden;',
    '  box-shadow:var(--jf-shadow);border:1px solid var(--jf-border);background:var(--jf-bg);}',
    '.jf-overlay-panel .jf-root{border-radius:12px;}'
  ].join('\n');

  /* ------------------------------------------------------------------ *
   * 图标
   * ------------------------------------------------------------------ */
  function svgIcon(paths, opts) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', (opts && opts.width) || 2);
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    for (var i = 0; i < paths.length; i++) {
      var p = document.createElementNS(SVG_NS, 'path');
      p.setAttribute('d', paths[i]);
      svg.appendChild(p);
    }
    return svg;
  }

  var ICONS = {
    collapseAll: ['M4 6h16', 'M4 12h9', 'M4 18h5'],
    expandAll: ['M4 6h16', 'M4 12h12', 'M4 18h8', 'M17 15l3 3 3-3'],
    copy: ['M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z',
      'M5 15V4a1 1 0 0 1 1-1h9'],
    download: ['M12 3.5v12', 'm7.5 11 4.5 4.5 4.5-4.5', 'M4.5 20.5h15'],
    search: ['M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14z', 'm20 20-3.6-3.6'],
    theme: ['M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z'],
    restore: ['M3.5 12a8.5 8.5 0 1 0 2.7-6.2', 'M3 4v5h5'],
    up: ['m6 15 6-6 6 6'],
    down: ['m6 9 6 6 6-6'],
    close: ['M6 6l12 12', 'M18 6 6 18']
  };

  /** 珊瑚红的圆角方框折叠标记：展开为「−」，折叠为「+」 */
  function toggleGlyph(expanded) {
    var svg = svgIcon(expanded ? ['M8.5 12h7'] : ['M8.5 12h7', 'M12 8.5v7'], { width: 1.9 });
    var rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', '2.6');
    rect.setAttribute('y', '2.6');
    rect.setAttribute('width', '18.8');
    rect.setAttribute('height', '18.8');
    rect.setAttribute('rx', '5.4');
    svg.insertBefore(rect, svg.firstChild);
    return svg;
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function installStyles(rootEl) {
    var doc = rootEl.ownerDocument;
    var rootNode = rootEl.getRootNode ? rootEl.getRootNode() : doc;
    var target = rootNode && rootNode.nodeType === 11 ? rootNode : doc.head || doc.documentElement;
    if (!target || rootEl.__jfStyled) return;
    if (target.querySelector && target.querySelector('style[data-jf-style]')) {
      rootEl.__jfStyled = true;
      return;
    }
    var style = doc.createElement('style');
    style.setAttribute('data-jf-style', '1');
    style.textContent = VIEWER_CSS;
    target.insertBefore(style, target.firstChild || null);
    rootEl.__jfStyled = true;
  }

  function escapeForDisplay(str) {
    return String(str).replace(/"/g, '\\"');
  }

  /* ------------------------------------------------------------------ *
   * createViewer
   * ------------------------------------------------------------------ */
  function createViewer(rootEl, userOptions) {
    var opts = Object.assign({}, NS.DEFAULTS, userOptions || {});
    var parser = NS.parser;

    var state = {
      text: '',
      root: null,
      error: null,
      lenient: false,
      outMode: 'pretty',
      hitMap: null,
      hits: [],
      cursor: -1,
      stats: { count: 0, depth: 0 }
    };

    var body, toolbar, statusBar, toastEl, hitsLabel, searchInput, pathLabel, statsLabel;

    rootEl.classList.add('jf-root');
    if (opts.overlay) rootEl.classList.add('jf-overlay');
    applyTheme();
    applyFont();
    installStyles(rootEl);

    toolbar = el('div', 'jf-toolbar');
    body = el('div', 'jf-body');
    statusBar = el('div', 'jf-status');
    toastEl = el('div', 'jf-toast');
    rootEl.appendChild(toolbar);
    rootEl.appendChild(body);
    rootEl.appendChild(statusBar);
    rootEl.appendChild(toastEl);

    buildToolbar();

    pathLabel = el('span', 'jf-path');
    pathLabel.title = '点击复制当前路径';
    pathLabel.addEventListener('click', function () {
      if (state.currentPath) doCopy(state.currentPath, '已复制路径');
    });
    statsLabel = el('span', '');
    statusBar.appendChild(pathLabel);
    statusBar.appendChild(statsLabel);

    /* ---------------- 工具栏 ---------------- */
    function tbtn(label, icon, title, handler, variant) {
      var b = el('button', 'jf-btn' + (variant ? ' jf-' + variant : '') + (label ? '' : ' jf-btn-icon'));
      b.type = 'button';
      b.title = title || label || '';
      if (icon) b.appendChild(svgIcon(ICONS[icon]));
      if (label) b.appendChild(el('span', null, label));
      b.addEventListener('click', handler);
      return b;
    }

    function select(options, value, title, onChange) {
      var sel = el('select', 'jf-select');
      sel.title = title || '';
      options.forEach(function (pair) {
        var o = el('option', null, pair[1]);
        o.value = pair[0];
        sel.appendChild(o);
      });
      sel.value = value;
      sel.addEventListener('change', function () { onChange(sel.value); });
      return sel;
    }

    function buildToolbar() {
      toolbar.textContent = '';

      toolbar.appendChild(tbtn(null, 'collapseAll', '折叠全部', function () {
        setAllExpanded(false);
      }));
      toolbar.appendChild(tbtn(null, 'expandAll', '展开全部', function () {
        setAllExpanded(true);
      }));

      var depthWrap = el('span', 'jf-field');
      depthWrap.appendChild(el('span', null, '展开到'));
      depthWrap.appendChild(select(
        [['1', '1 层'], ['2', '2 层'], ['3', '3 层'], ['4', '4 层'], ['5', '5 层'], ['8', '8 层']],
        String(opts.expandDepth), '打开时自动展开的层级',
        function (v) {
          opts.expandDepth = parseInt(v, 10);
          expandToDepth(opts.expandDepth);
          persist({ expandDepth: opts.expandDepth });
        }
      ));
      toolbar.appendChild(depthWrap);

      toolbar.appendChild(el('div', 'jf-sep'));

      var searchWrap = el('span', 'jf-search');
      searchWrap.appendChild(svgIcon(ICONS.search, { width: 2.2 })).classList.add('jf-search-icon');
      searchInput = el('input');
      searchInput.type = 'text';
      searchInput.placeholder = '搜索键或值…';
      searchInput.setAttribute('spellcheck', 'false');
      var timer = null;
      searchInput.addEventListener('input', function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () { performSearch(searchInput.value.trim()); }, 180);
      });
      searchInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          jump(e.shiftKey ? -1 : 1);
        } else if (e.key === 'Escape') {
          searchInput.value = '';
          performSearch('');
        }
      });
      searchWrap.appendChild(searchInput);
      toolbar.appendChild(searchWrap);

      hitsLabel = el('span', 'jf-hits');
      toolbar.appendChild(hitsLabel);
      toolbar.appendChild(tbtn(null, 'up', '上一个匹配（Shift+Enter）', function () { jump(-1); }));
      toolbar.appendChild(tbtn(null, 'down', '下一个匹配（Enter）', function () { jump(1); }));

      toolbar.appendChild(el('div', 'jf-sep'));

      var escapeWrap = el('label', 'jf-check');
      escapeWrap.title = '勾选：原样显示 \\n、\\uXXXX 等转义写法；取消：还原为真实字符';
      var escapeBox = el('input');
      escapeBox.type = 'checkbox';
      escapeBox.checked = !!opts.keepEscape;
      escapeBox.addEventListener('change', function () {
        opts.keepEscape = escapeBox.checked;
        persist({ keepEscape: opts.keepEscape });
        render();
        if (searchInput.value.trim()) performSearch(searchInput.value.trim());
      });
      escapeWrap.appendChild(escapeBox);
      escapeWrap.appendChild(el('span', null, '保留转义'));
      toolbar.appendChild(escapeWrap);

      toolbar.appendChild(el('div', 'jf-spacer'));

      toolbar.appendChild(select(
        [['auto', '跟随系统'], ['light', '浅色'], ['dark', '深色']],
        opts.theme, '主题',
        function (v) {
          opts.theme = v;
          applyTheme();
          persist({ theme: v });
        }
      ));

      toolbar.appendChild(select(
        [['pretty', '美化'], ['compact', '压缩']],
        state.outMode, '复制 / 下载时的输出格式',
        function (v) { state.outMode = v; updateStats(); }
      ));

      toolbar.appendChild(select(
        [['2', '2 空格'], ['4', '4 空格'], ['tab', 'Tab']],
        String(opts.indent), '缩进宽度',
        function (v) {
          opts.indent = v === 'tab' ? 'tab' : parseInt(v, 10);
          persist({ indent: opts.indent });
          updateStats();
        }
      ));

      if (typeof opts.onRestore === 'function') {
        toolbar.appendChild(tbtn('还原原文', 'restore', '关闭格式化，显示网页原始内容',
          function () { opts.onRestore(); }));
      }
      if (typeof opts.onClose === 'function') {
        toolbar.appendChild(tbtn(null, 'close', '关闭', function () { opts.onClose(); }));
      }

      toolbar.appendChild(tbtn('复制', 'copy', '复制格式化后的 JSON',
        function () { doCopy(outputText(), '已复制 ' + formatBytes(outputText().length)); },
        'btn-primary'));
      toolbar.appendChild(tbtn('下载', 'download', '下载为 .json 文件',
        function () { downloadJson(); }, 'btn-outline'));
    }

    /* ---------------- 主题与字号 ---------------- */
    var mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function applyTheme() {
      var theme = opts.theme;
      if (theme === 'auto') theme = mql && mql.matches ? 'dark' : 'light';
      rootEl.setAttribute('data-theme', theme);
    }

    if (mql && mql.addEventListener) {
      mql.addEventListener('change', function () {
        if (opts.theme === 'auto') applyTheme();
      });
    }

    function applyFont() {
      var size = parseInt(opts.fontSize, 10);
      if (!size || size < 8) size = DEFAULT_FONT_SIZE;
      rootEl.style.fontSize = size + 'px';
      // 取消「等宽字体」时换成正文字体栈：同字号下字形更大、笔画更实
      rootEl.style.fontFamily = opts.monoFont === false ? PROSE_FONT : MONO_FONT;
    }

    function persist(patch) {
      if (typeof opts.onSettingsChange === 'function') opts.onSettingsChange(patch);
    }

    /* ---------------- 文本呈现 ---------------- */
    function keyText(keyNode) {
      if (!keyNode) return '';
      return opts.keepEscape ? keyNode.raw : '"' + escapeForDisplay(keyNode.value) + '"';
    }

    function valueText(node) {
      if (node.type === 'string') {
        return opts.keepEscape ? node.raw : '"' + escapeForDisplay(node.value) + '"';
      }
      return node.raw;
    }

    function nodeValueClass(node) {
      switch (node.type) {
        case 'string': return 'jf-str';
        case 'number': return 'jf-num';
        case 'boolean': return 'jf-bool';
        case 'null': return 'jf-null';
        default: return '';
      }
    }

    function summaryText(node) {
      if (node.type === 'object') {
        var n = node.entries.length;
        return n === 0 ? '{}' : '… ' + n + ' 个字段';
      }
      var m = node.items.length;
      return m === 0 ? '[]' : '… ' + m + ' 项';
    }

    /* ---------------- 渲染 ---------------- */
    function orderedEntries(node) {
      if (!opts.sortKeys) return node.entries;
      return node.entries.slice().sort(function (a, b) {
        return a.keyNode.value.localeCompare(b.keyNode.value, 'zh-Hans-CN');
      });
    }

    function makeRow(node, depth) {
      var row = el('div', 'jf-row');
      if (node) row.setAttribute('data-jf-node', String(node.id));
      row.style.setProperty('--jf-depth', String(depth || 0));
      var gut = el('span', 'jf-no');
      if (!opts.lineNumbers) gut.style.display = 'none';
      row.appendChild(gut);
      return row;
    }

    function makeToggle(expanded) {
      var b = el('button', 'jf-toggle');
      b.type = 'button';
      b.title = expanded ? '折叠' : '展开';
      b.appendChild(toggleGlyph(expanded));
      return b;
    }

    function setToggleIcon(btn, expanded) {
      btn.title = expanded ? '折叠' : '展开';
      btn.textContent = '';
      btn.appendChild(toggleGlyph(expanded));
    }

    function makeKeySpan(keyNode, path) {
      var span = el('span', 'jf-key');
      highlightInto(span, keyText(keyNode), state.hitMap ? state.hitMap.term : '');
      var fullPath = path || keyNode.value;
      span.title = '点击复制路径：' + fullPath;
      span.addEventListener('click', function (e) {
        e.stopPropagation();
        doCopy(fullPath, '已复制路径：' + fullPath);
      });
      return span;
    }

    function renderNode(parentEl, node, keyNode, isLast, path, depth) {
      depth = depth || 0;
      var isContainer = node.type === 'object' || node.type === 'array';
      var childCount = isContainer
        ? (node.type === 'object' ? node.entries.length : node.items.length)
        : 0;

      if (isContainer && childCount > 0) {
        var open = makeRow(node, depth);
        var content = el('span', 'jf-content');
        var toggle = makeToggle(node.expanded);

        if (keyNode) {
          content.appendChild(makeKeySpan(keyNode, path));
          content.appendChild(el('span', 'jf-punct', ': '));
        }
        // 折叠标记位于键与括号之间，与参考设计一致
        content.appendChild(toggle);
        content.appendChild(el('span', 'jf-punct', node.type === 'object' ? '{' : '['));
        var sum = el('span', 'jf-summary', summaryText(node));
        sum.title = '点击展开';
        if (node.expanded) sum.style.display = 'none';
        content.appendChild(sum);
        open.appendChild(content);
        parentEl.appendChild(open);

        var kids = el('div', 'jf-children');
        parentEl.appendChild(kids);
        if (!node.expanded) kids.classList.add('jf-children-collapsed');
        else fillChildren(kids, node, path, depth);

        var closeRow = makeRow(node, depth);
        var closeContent = el('span', 'jf-content');
        closeContent.appendChild(el('span', 'jf-punct', node.type === 'object' ? '}' : ']'));
        if (!isLast) closeContent.appendChild(el('span', 'jf-punct', ','));
        closeRow.appendChild(closeContent);
        parentEl.appendChild(closeRow);

        function toggleNode() {
          node.expanded = !node.expanded;
          setToggleIcon(toggle, node.expanded);
          sum.style.display = node.expanded ? 'none' : '';
          kids.classList.toggle('jf-children-collapsed', !node.expanded);
          if (node.expanded) fillChildren(kids, node, path, depth);
          renumber();
          updateStats();
        }
        toggle.addEventListener('click', toggleNode);
        sum.addEventListener('click', toggleNode);
        return;
      }

      // 基本类型，或空对象 / 空数组
      var row = makeRow(node, depth);
      var rowContent = el('span', 'jf-content');
      if (keyNode) {
        rowContent.appendChild(makeKeySpan(keyNode, path));
        rowContent.appendChild(el('span', 'jf-punct', ': '));
      }
      if (isContainer) {
        rowContent.appendChild(el('span', 'jf-punct', node.type === 'object' ? '{}' : '[]'));
      } else {
        var v = el('span', nodeValueClass(node));
        highlightInto(v, valueText(node), state.hitMap ? state.hitMap.term : '');
        v.title = '点击复制值';
        v.style.cursor = 'pointer';
        v.addEventListener('click', function () { doCopy(valueText(node), '已复制值'); });
        rowContent.appendChild(v);
      }
      if (!isLast) rowContent.appendChild(el('span', 'jf-punct', ','));
      row.appendChild(rowContent);
      parentEl.appendChild(row);
    }

    function fillChildren(kidsEl, node, path, depth) {
      if (kidsEl.__jfFilled) return;
      var frag = body.ownerDocument.createDocumentFragment();
      var child = depth + 1;
      if (node.type === 'object') {
        var entries = orderedEntries(node);
        for (var i = 0; i < entries.length; i++) {
          renderNode(
            frag, entries[i].value, entries[i].keyNode, i === entries.length - 1,
            parser.joinKey(path, entries[i].keyNode.value), child
          );
        }
      } else {
        for (var j = 0; j < node.items.length; j++) {
          renderNode(frag, node.items[j], null, j === node.items.length - 1,
            path + '[' + j + ']', child);
        }
      }
      kidsEl.textContent = '';
      kidsEl.appendChild(frag);
      kidsEl.__jfFilled = true;
    }

    function highlightInto(span, text, term) {
      if (!term) {
        span.textContent = text;
        return;
      }
      var lower = text.toLowerCase();
      var needle = term.toLowerCase();
      var idx = 0;
      var n = 0;
      span.textContent = '';
      while (true) {
        var at = lower.indexOf(needle, idx);
        if (at === -1) break;
        if (at > idx) span.appendChild(span.ownerDocument.createTextNode(text.slice(idx, at)));
        var mk = el('span', 'jf-mark');
        mk.textContent = text.slice(at, at + needle.length);
        span.appendChild(mk);
        idx = at + needle.length;
        n++;
      }
      if (idx < text.length) span.appendChild(span.ownerDocument.createTextNode(text.slice(idx)));
      if (n === 0) span.textContent = text;
    }

    function renumber() {
      var gutt = body.querySelectorAll('.jf-no');
      var k = 0;
      for (var i = 0; i < gutt.length; i++) {
        if (!isVisible(gutt[i])) continue;
        k++;
        gutt[i].textContent = opts.lineNumbers ? String(k) : '';
      }
    }

    function isVisible(node) {
      var cur = node;
      while (cur && cur !== body) {
        if (cur.hidden || (cur.classList && cur.classList.contains('jf-children-collapsed')) ||
            (cur.style && cur.style.display === 'none')) {
          return false;
        }
        cur = cur.parentElement;
      }
      return true;
    }

    function renderError() {
      var err = state.error;
      var box = el('div', 'jf-error');
      box.appendChild(el('h3', null, 'JSON 解析失败'));
      box.appendChild(el('p', null, err.message));
      var pre = el('pre');
      pre.appendChild(document.createTextNode(String(err.lineText || '')));
      pre.appendChild(document.createTextNode('\n'));
      pre.appendChild(el('span', 'jf-caret', err.caret));
      box.appendChild(pre);
      box.appendChild(el('p', 'jf-meta', '第 ' + err.line + ' 行，第 ' + err.column + ' 列'));
      var retry = el('button', 'jf-btn jf-btn-outline', '尝试宽松解析');
      retry.type = 'button';
      retry.title = '自动去掉注释、单引号、尾随逗号和未加引号的键名后重试';
      retry.addEventListener('click', function () {
        try {
          var res = parser.parse(state.text, { lenient: true });
          state.root = res.root;
          state.lenient = true;
          state.error = null;
          afterParse();
        } catch (e) {
          toast('宽松解析仍然失败');
        }
      });
      box.appendChild(retry);
      body.appendChild(box);
    }

    function render() {
      body.textContent = '';
      body.scrollTop = 0;
      if (state.error) {
        renderError();
        updateStats();
        return;
      }
      if (!state.root) {
        body.appendChild(el('div', 'jf-empty', '没有可显示的内容'));
        updateStats();
        return;
      }
      var frag = body.ownerDocument.createDocumentFragment();
      renderNode(frag, state.root, null, true, '$', 0);
      body.appendChild(frag);
      renumber();
      updateStats();
    }

    /* ---------------- 折叠控制 ---------------- */
    function setAllExpanded(expanded) {
      if (!state.root) return;
      parser.walk(state.root, function (node) {
        if (node.type === 'object' || node.type === 'array') node.expanded = expanded;
      });
      render();
    }

    function expandToDepth(depth) {
      if (!state.root) return;
      parser.walk(state.root, function (node) {
        if (node.type === 'object' || node.type === 'array') node.expanded = node.depth < depth;
      });
      render();
    }

    function expandAncestors(node) {
      var cur = node.parent;
      while (cur) {
        cur.expanded = true;
        cur = cur.parent;
      }
    }

    /* ---------------- 搜索 ---------------- */
    function performSearch(term) {
      state.hits = [];
      state.cursor = -1;
      state.hitMap = term ? { term: term } : null;

      if (!term || !state.root) {
        hitsLabel.textContent = '';
        render();
        return;
      }

      var needle = term.toLowerCase();
      var pending = [];
      var isLeaf = function (node) {
        return node.type !== 'object' && node.type !== 'array';
      };
      parser.walk(state.root, function (node) {
        var matched = false;
        // 键名命中
        if (node.keyNode) {
          if (keyText(node.keyNode).toLowerCase().indexOf(needle) !== -1 ||
              node.keyNode.value.toLowerCase().indexOf(needle) !== -1) {
            matched = true;
          }
        }
        // 值命中：容器不按原文匹配，否则根节点会因整段文本而永远命中
        if (!matched && isLeaf(node)) {
          if (valueText(node).toLowerCase().indexOf(needle) !== -1) matched = true;
          else if (node.type === 'string' && node.value.toLowerCase().indexOf(needle) !== -1) matched = true;
        }
        if (matched) pending.push(node);
      });

      state.hits = pending;
      if (pending.length && pending.length <= 300) {
        for (var i = 0; i < pending.length; i++) expandAncestors(pending[i]);
      }
      render();

      if (!pending.length) {
        hitsLabel.textContent = '无匹配';
        return;
      }
      jumpTo(0, true);
    }

    function jumpTo(index, silent) {
      if (!state.hits.length) return;
      var n = state.hits.length;
      state.cursor = ((index % n) + n) % n;
      var node = state.hits[state.cursor];
      var row = body.querySelector('[data-jf-node="' + node.id + '"]');
      hitsLabel.textContent = (state.cursor + 1) + '/' + n;
      if (row) {
        var prev = body.querySelector('.jf-flash');
        if (prev) prev.classList.remove('jf-flash');
        row.classList.add('jf-flash');
        try {
          row.scrollIntoView({ block: 'center', behavior: silent ? 'auto' : 'smooth' });
        } catch (e) {
          row.scrollIntoView();
        }
      }
      setPath(node.path);
    }

    function jump(delta) {
      if (!state.hits.length) return;
      jumpTo(state.cursor + delta, false);
    }

    function setPath(p) {
      state.currentPath = p || '';
      pathLabel.textContent = '';
      if (!p) return;
      pathLabel.appendChild(document.createTextNode('路径 '));
      pathLabel.appendChild(el('b', null, p));
    }

    /* ---------------- 输出 ---------------- */
    function compact(node) {
      if (node.type === 'object') {
        if (!node.entries.length) return '{}';
        var es = orderedEntries(node);
        var parts = [];
        for (var i = 0; i < es.length; i++) {
          parts.push(es[i].keyNode.raw + ':' + compact(es[i].value));
        }
        return '{' + parts.join(',') + '}';
      }
      if (node.type === 'array') {
        if (!node.items.length) return '[]';
        var arr = [];
        for (var j = 0; j < node.items.length; j++) arr.push(compact(node.items[j]));
        return '[' + arr.join(',') + ']';
      }
      return node.raw;
    }

    function pretty(node, unit, depth) {
      var pad = new Array(depth + 1).join(unit);
      var padIn = new Array(depth + 2).join(unit);
      if (node.type === 'object') {
        if (!node.entries.length) return '{}';
        var es = orderedEntries(node);
        var parts = [];
        for (var i = 0; i < es.length; i++) {
          parts.push(padIn + es[i].keyNode.raw + ': ' + pretty(es[i].value, unit, depth + 1));
        }
        return '{\n' + parts.join(',\n') + '\n' + pad + '}';
      }
      if (node.type === 'array') {
        if (!node.items.length) return '[]';
        var arr = [];
        for (var j = 0; j < node.items.length; j++) {
          arr.push(padIn + pretty(node.items[j], unit, depth + 1));
        }
        return '[\n' + arr.join(',\n') + '\n' + pad + ']';
      }
      return node.raw;
    }

    function outputText() {
      if (!state.root) return state.text || '';
      if (state.outMode === 'compact') return compact(state.root);
      return pretty(state.root, NS.indentUnit(opts.indent), 0);
    }

    function doCopy(text, message) {
      if (!text) return;
      var done = function () { toast(message || '已复制'); };
      var fallback = function () {
        try {
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.setAttribute('readonly', '');
          ta.style.position = 'fixed';
          ta.style.top = '-1000px';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          ta.remove();
          done();
        } catch (e) {
          toast('复制失败，请手动选择文本');
        }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
    }

    function downloadJson() {
      var text = outputText();
      var name = (opts.fileNamePrefix || 'data') + '.json';
      try {
        var blob = new Blob([text], { type: 'application/json;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = name;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 3000);
        toast('已开始下载 ' + name);
      } catch (e) {
        toast('下载失败');
      }
    }

    /* ---------------- 提示与状态 ---------------- */
    var toastTimer = null;
    function toast(message) {
      toastEl.textContent = message;
      toastEl.classList.add('jf-toast-show');
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(function () {
        toastEl.classList.remove('jf-toast-show');
      }, 1800);
    }

    function formatBytes(n) {
      if (n < 1024) return n + ' B';
      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
      return (n / 1024 / 1024).toFixed(2) + ' MB';
    }

    function updateStats() {
      if (!state.root) {
        statsLabel.textContent = '';
        return;
      }
      statsLabel.textContent =
        state.stats.count + ' 个节点 · 深度 ' + state.stats.depth +
        ' · 源码 ' + formatBytes(state.text.length) +
        ' · 输出 ' + formatBytes(outputText().length);
    }

    function afterParse() {
      state.stats = parser.stats(state.root);
      state.hitMap = null;
      state.hits = [];
      state.cursor = -1;
      if (searchInput) {
        searchInput.value = '';
      }
      if (hitsLabel) hitsLabel.textContent = '';
      expandToDepth(opts.expandDepth);
      setPath('');
    }

    /* ---------------- 对外接口 ---------------- */
    function setText(text, options) {
      options = options || {};
      state.text = typeof text === 'string' ? text : String(text == null ? '' : text);
      state.error = null;
      state.root = null;
      state.lenient = false;
      try {
        var res = parser.parse(state.text, { lenient: !!options.lenient });
        state.root = res.root;
        state.lenient = res.lenient;
      } catch (err) {
        state.error = err;
        state.stats = { count: 0, depth: 0 };
        render();
        return false;
      }
      // 渲染阶段的异常不应被误报为 JSON 语法错误
      afterParse();
      return true;
    }

    function updateOptions(patch) {
      Object.assign(opts, patch || {});
      applyTheme();
      applyFont();
      if (state.root) {
        render();
        if (searchInput && searchInput.value.trim()) performSearch(searchInput.value.trim());
      }
    }

    function destroy() {
      if (toastTimer) clearTimeout(toastTimer);
      if (rootEl && rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
    }

    return {
      setText: setText,
      updateOptions: updateOptions,
      destroy: destroy,
      outputText: outputText,
      toast: toast,
      getState: function () { return state; },
      rootEl: rootEl
    };
  }

  NS.createViewer = createViewer;
  NS.VIEWER_CSS = VIEWER_CSS;
})();
