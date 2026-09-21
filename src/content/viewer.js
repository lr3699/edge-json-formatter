/**
 * JSON 查看器：语法高亮 + 可折叠树（默认全展开）+ 路径复制 + 转义保留/还原 + 主题。
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
   *
   * 末尾那串中文字体是**必须显式列出**的，不能只靠 generic monospace 兜底：
   * Cascadia Mono / Consolas / Courier New 全都没有汉字，不列中文时 Chromium
   * 会走 `monospace` 的 CJK 兜底，而 Windows 上这个兜底恰好落到 NSimSun
   * （新宋体，点阵宋体系）——15px 下中文就是又细又虚的宋体轮廓，这正是
   * 「格式化后中文模糊看不清」的根因（已用 CSS.getPlatformFontsForNode 实测确认）。
   * 列出中文字体后：拉丁字符仍走最前面的等宽字体（代码对齐不受影响），
   * 汉字由第一个命中的中文字体渲染。微软雅黑 / PingFang / Noto Sans SC
   * 都是为屏幕阅读设计的无衬线体，笔画实、hinting 好，同字号下清晰得多。
   */
  var MONO_FONT = '"Cascadia Mono",Consolas,ui-monospace,SFMono-Regular,"SF Mono",' +
                  'Menlo,"Liberation Mono","Courier New",' +
                  '"Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Hiragino Sans GB",' +
                  '"Noto Sans SC","Source Han Sans SC","WenQuanYi Micro Hei",sans-serif';
  /** 取消「等宽字体」时使用：同字号下观感更大、笔画更实 */
  var PROSE_FONT = 'system-ui,-apple-system,"Segoe UI","Microsoft YaHei UI",' +
                   '"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif';

  /**
   * 正文字号兜底值（px），与 defaults.js 的 fontSize 保持一致。
   * 14px 是「不显大、又够清晰」的平衡点：再小（≤13px）中文在 Windows 上
   * 笔画会挤在一起，再大则一屏能看的行数明显减少。
   */
  var DEFAULT_FONT_SIZE = 14;

  /** 正文行高 = round(字号 × 1.7)，在 applyFont 里按实际字号算成整数 px */
  var LINE_RATIO = 1.7;

  /**
   * 分批渲染上限（大 JSON 卡死修复）：
   *  - MAX_CHUNK：展开 / 「加载更多」一次同步建多少行，超出部分交给
   *    「还有 N 项」哨兵 + 后台分帧续建；
   *  - PAINT_ROWS / FILL_ROWS：首帧同步建多少行立刻上屏、之后每帧补建多少行。
   *    实测 11MB JSON 一次性建 5700 行（4 万+ 节点）样式重算 + 布局近 500ms，
   *    主线程整段卡死——分帧后首屏 ~50ms 即可见，其余行在后台补齐，期间
   *    浏览器每帧都能响应输入与滚动。
   */
  var MAX_CHUNK = 400;
  var PAINT_ROWS = 400;
  var FILL_ROWS = 350;
  /** 一次渲染允许存在的总行数上限。分帧只解决「卡不卡」，不解决「该不该全建」：
      11MB 全展开是十几万行 / 百万级节点，内存和滚动都会崩，超出部分走哨兵。 */
  var TOTAL_ROWS = 6000;

  /* ------------------------------------------------------------------ *
   * 样式
   * ------------------------------------------------------------------ */
  var VIEWER_CSS = [
    '.jf-root{all:initial;}',
    '.jf-root{',
    '  --jf-indent:' + INDENT_PX + 'px;',
    '  --jf-lh:' + Math.round(DEFAULT_FONT_SIZE * LINE_RATIO) + 'px;',
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
    '  --jf-shadow:0 12px 48px rgba(15,23,42,.18);',
    '  position:relative;display:flex;flex-direction:column;height:100%;width:100%;',
    '  background:var(--jf-bg);color:var(--jf-text);',
    '  font-family:' + MONO_FONT + ';',
    '  font-size:' + DEFAULT_FONT_SIZE + 'px;line-height:var(--jf-lh);letter-spacing:normal;text-align:left;',
    /* font-weight 用 400：中文无衬线体（雅黑/PingFang）只为屏幕优化了 400 与 700
       两档，请求 500 这类「中间字重」要么被映射掉、要么被合成加粗，合成加粗会把
       笔画糊在一起——那正是「字很清楚但看着虚」的来源。400 是笔画最干净的一档。
       font-synthesis-weight:none 再兜一道：任何情况下都不允许伪造字重。 */
    '  direction:ltr;font-weight:400;font-style:normal;text-transform:none;',
    '  font-synthesis-weight:none;',
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
    '  --jf-shadow:0 12px 48px rgba(0,0,0,.55);',
    '}',
    '.jf-root *,.jf-root *::before,.jf-root *::after{box-sizing:border-box;}',
    /* macOS 深色下用灰阶抗锯齿：浅色文字在深底上默认会显得偏重、发糊。
       其它平台保持 auto，Windows 的 ClearType 比灰阶更清晰。 */
    '.jf-root.is-mac[data-theme="dark"]{-webkit-font-smoothing:antialiased;',
    '  -moz-osx-font-smoothing:grayscale;}',

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
    /* 工具栏主功能按钮：实心描边，视觉上与正文区分，凸显可点击 */
    '.jf-btn-solid{height:30px;padding:0 12px;border:1px solid var(--jf-border-strong);',
    '  border-radius:8px;background:var(--jf-bg);color:var(--jf-text);font-size:12.5px;font-weight:600;',
    '  box-shadow:0 1px 2px rgba(0,0,0,.06);}',
    '.jf-btn-solid:hover:not([disabled]){border-color:var(--jf-accent);',
    '  background:var(--jf-accent-soft);color:var(--jf-accent);}',
    /* 启用状态：保留转义开启 / 输出为压缩 / 手动指定主题 */
    '.jf-btn-solid.jf-btn-on{border-color:var(--jf-accent);background:var(--jf-accent-soft);',
    '  color:var(--jf-accent);}',


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
    /* 行号用整数 px + 与正文同一个行高变量：行号不再是 .86em 这种小数尺寸
       （14×.86 = 12.04px，落在分数设备像素上会发虚），也顺带修掉了行号
       与正文行高不一致导致的逐行错位。 */
    '  opacity:.6;user-select:none;font-size:12px;line-height:var(--jf-lh);background:var(--jf-bg);',
    '  position:relative;',
    '  /* 行号要钉在查看器最左侧。不能用负 margin：flex 里首项的负 margin 会把',
    '     后面的内容一起拖过去，正好抵消 .jf-children 的嵌套缩进，开了行号整棵树',
    '     就变平了。用 relative + left 只挪行号自己，不影响兄弟元素布局。每层实际',
    '     横向开销 = --jf-indent + .jf-children 的 margin-left(2px) + 左边框(1px)，',
    '     再补上 .jf-row 自身的 padding-left(3px)。 */',
    '  left:calc(var(--jf-indent) * var(--jf-depth,0) * -1 - var(--jf-depth,0) * 3px - 3px);}',
    '.jf-content{flex:1 1 auto;min-width:0;}',

    /* 折叠子层：用嵌套容器 + 左侧引导线表达层级 */
    '.jf-children{padding-left:var(--jf-indent);border-left:1px solid var(--jf-guide);',
    '  margin-left:2px;}',
    '.jf-children-collapsed{display:none;}',

    /* 压缩显示：不改动树形 DOM，只靠 CSS 把嵌套结构塌缩成单行。
       大 JSON 点「压缩」时零节点重建，几十万节点也能瞬间切换。 */
    '.jf-compact .jf-row{display:inline;padding:0;}',
    '.jf-compact .jf-children{display:inline;padding-left:0;border-left:0;margin-left:0;}',
    '.jf-compact .jf-no,.jf-compact .jf-toggle,.jf-compact .jf-summary{display:none;}',
    '.jf-compact .jf-row:hover{background:none;}',

    /* 键与括号之间的圆角方框折叠标记 */
    '.jf-toggle{display:inline-flex;align-items:center;justify-content:center;',
    '  width:15px;height:15px;margin:0 3px;padding:0;border:0;background:none;',
    '  color:var(--jf-toggle);cursor:pointer;vertical-align:-2.5px;}',
    '.jf-toggle svg{width:14px;height:14px;display:block;pointer-events:none;}',
    '.jf-toggle:hover{color:var(--jf-toggle-hover);}',

    '.jf-key{color:var(--jf-key);font-weight:600;cursor:pointer;border-radius:3px;}',
    '.jf-key:hover{background:var(--jf-key-bg,rgba(146,39,143,.09));}',
    '.jf-str{color:var(--jf-str);}',
    '.jf-str-more{color:var(--jf-accent);cursor:pointer;font-style:italic;',
    '  user-select:none;margin-left:4px;}',
    '.jf-str-more:hover{text-decoration:underline;}',
    '.jf-num{color:var(--jf-num);}',
    '.jf-bool{color:var(--jf-bool);}',
    '.jf-null{color:var(--jf-null);font-style:italic;}',
    '.jf-punct{color:var(--jf-punct);}',
    '.jf-summary{color:var(--jf-muted);font-style:italic;font-size:13px;cursor:pointer;}',
    '.jf-summary:hover{color:var(--jf-accent);}',

    /* ---------------- 状态栏 ---------------- */
    '.jf-status{flex:0 0 auto;display:flex;align-items:center;gap:12px;padding:6px 24px 6px 14px;',
    '  border-top:1px solid var(--jf-border);background:var(--jf-bg-alt);',
    '  font-size:12px;color:var(--jf-muted);overflow:hidden;}',
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
    '  font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei UI","Microsoft YaHei",' +
    '"PingFang SC","Noto Sans SC",sans-serif;}',
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
    copy: ['M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z',
      'M5 15V4a1 1 0 0 1 1-1h9'],
    download: ['M12 3.5v12', 'm7.5 11 4.5 4.5 4.5-4.5', 'M4.5 20.5h15'],
    theme: ['M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z']
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
      stats: { count: 0, depth: 0 }
    };

    var body, toolbar, statusBar, toastEl, pathLabel, statsLabel;

    /**
     * 渲染会话：可恢复的深度优先遍历状态。
     * stack 里是待填充的容器帧，budget 是本帧还能建多少行，timer 是续建定时器。
     * numbering=true 表示「建行时直接按文档序赋行号」（整树重渲染）；
     * 展开/折叠只动局部，行号统一交给 renumber()，此时为 false。
     */
    var session = { stack: [], lines: 0, budget: 0, total: 0, timer: null,
                    numbering: true, late: false };
    var renderToken = 0;
    /** 输出文本缓存：outputText() 的结果按「模式+缩进」缓存，避免每次统计都全树序列化 */
    var outCache = { key: null, text: '' };

    rootEl.classList.add('jf-root');
    if (opts.overlay) rootEl.classList.add('jf-overlay');
    /* macOS 深色主题下默认的字体平滑会把浅色文字渲染得偏重、边缘发糊，
       CSS 里对 .is-mac[data-theme="dark"] 降级成灰阶抗锯齿。
       只给 macOS 加这个类：Windows/Linux 上 ClearType 渲染本来就利落，
       改成灰阶抗锯齿反而会让笔画变细。 */
    if (/Mac/i.test((navigator.platform || '') + ' ' + (navigator.userAgent || ''))) {
      rootEl.classList.add('is-mac');
    }
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

    var THEME_NAMES = { auto: '跟随系统', light: '浅色', dark: '深色' };
    var THEME_ORDER = ['auto', 'light', 'dark'];
    /** 工具栏控件引用，供 syncToolbar() 刷新文案与选中态 */
    var tb = {};

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
      if (label) {
        var sp = el('span', null, label);
        b.__jfLabel = sp;
        b.appendChild(sp);
      }
      b.addEventListener('click', handler);
      return b;
    }

    function setBtnLabel(btn, text) {
      if (btn && btn.__jfLabel) btn.__jfLabel.textContent = text;
    }

    function buildToolbar() {
      toolbar.textContent = '';

      tb.escape = tbtn('保留转义', null, '', function () {
        opts.keepEscape = !opts.keepEscape;
        persist({ keepEscape: opts.keepEscape });
        syncToolbar();
        render();
      }, 'btn-solid');
      toolbar.appendChild(tb.escape);

      tb.theme = tbtn('主题', 'theme', '', function () {
        var i = THEME_ORDER.indexOf(opts.theme);
        opts.theme = THEME_ORDER[(i < 0 ? 0 : i + 1) % THEME_ORDER.length];
        applyTheme();
        persist({ theme: opts.theme });
        syncToolbar();
      }, 'btn-solid');
      toolbar.appendChild(tb.theme);

      tb.mode = tbtn('压缩', null, '', function () {
        state.outMode = state.outMode === 'compact' ? 'pretty' : 'compact';
        outCache.key = null;   // 输出模式变了，序列化缓存失效
        syncToolbar();
        // 只切 CSS class，不重建 DOM：大 JSON 几十万节点也能瞬间切换
        body.classList.toggle('jf-compact', state.outMode === 'compact');
      }, 'btn-solid');
      toolbar.appendChild(tb.mode);

      toolbar.appendChild(el('div', 'jf-spacer'));

      tb.copy = tbtn('复制', 'copy', '复制当前输出（美化 / 压缩）', function () {
        var t = outputText();
        doCopy(t, '已复制 ' + formatBytes(t.length));
      }, 'btn-primary');
      toolbar.appendChild(tb.copy);

      tb.download = tbtn('下载', 'download', '下载为 .json 文件', function () {
        downloadJson();
      }, 'btn-outline');
      toolbar.appendChild(tb.download);

      syncToolbar();
    }

    /** 刷新三个切换按钮的文案与高亮态（保留转义 / 主题 / 压缩） */
    function syncToolbar() {
      if (tb.escape) {
        tb.escape.classList.toggle('jf-btn-on', !!opts.keepEscape);
        tb.escape.title = opts.keepEscape
          ? '保留转义：已开启（点击关闭，\\n、\\uXXXX 还原为真实字符）'
          : '保留转义：已关闭（点击开启，原样显示 \\n、\\uXXXX 等写法）';
      }
      if (tb.theme) {
        setBtnLabel(tb.theme, THEME_NAMES[opts.theme] || '主题');
        tb.theme.classList.toggle('jf-btn-on', opts.theme !== 'auto');
        tb.theme.title = '主题：' + (THEME_NAMES[opts.theme] || '跟随系统') + '（点击切换）';
      }
      if (tb.mode) {
        var compact = state.outMode === 'compact';
        setBtnLabel(tb.mode, compact ? '压缩' : '美化');
        tb.mode.classList.toggle('jf-btn-on', compact);
        tb.mode.title = compact
          ? '输出：压缩（单行）——点击切换为美化'
          : '输出：美化（缩进展开）——点击切换为压缩';
      }
    }

    /* ---------------- 主题与字号 ---------------- */
    var mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function applyTheme() {
      var theme = opts.theme;
      if (theme === 'auto') theme = mql && mql.matches ? 'dark' : 'light';
      rootEl.setAttribute('data-theme', theme);
      // 通知宿主（如独立编辑页）同步全局主题；接管网页时宿主不接这个回调即可
      if (typeof opts.onThemeChange === 'function') opts.onThemeChange(theme, opts.theme);
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
      // 行高跟着字号走，但取整成 px：小数行高会让每一行的基线落在分数设备
      // 像素上，整段文字读起来就是「发虚」。14px 字号 → 24px 行高。
      rootEl.style.setProperty('--jf-lh', Math.round(size * LINE_RATIO) + 'px');
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

    /**
     * 超长字符串值：默认折叠 + 惰性展开，绝不一次性渲染全文。
     *
     * 这是「压缩 / 转义后大 JSON 卡死」的根因修复：压缩 / 转义后的内容往往
     * 是一个几 MB 的字符串值，如果一次性渲染全文（无论单个节点还是切成几千
     * 块），浏览器 shaping/layout 都会假死。正确做法是「惰性展开」：
     *  - 默认只渲染前 STRING_PREVIEW 字符，末尾挂「… (N 字符) 点击展开」；
     *  - 用户点「展开」才把全文分片渲染出来（块大小足够大，节点数可控）；
     *  - 展开后点「收起」再折叠回预览。
     * 这样转义 12MB 文本时，初始只产生 1 个文本节点 + 1 个折叠标记，
     * 主线程零阻塞。
     */
    var STRING_PREVIEW = 1024;
    var STRING_CHUNK = 8192;
    function appendValueText(container, node) {
      var text = valueText(node);
      if (text.length <= STRING_PREVIEW) {
        container.appendChild(document.createTextNode(text));
        return;
      }

      // 折叠态：预览 + 展开标记
      var preview = el('span', 'jf-str-trunc');
      preview.appendChild(document.createTextNode(text.slice(0, STRING_PREVIEW)));
      var more = el('span', 'jf-str-more');
      more.textContent = '… (' + text.length.toLocaleString('zh-CN') + ' 字符，点击展开)';
      more.title = '点击展开完整内容';
      preview.appendChild(more);
      container.appendChild(preview);

      var expanded = false;
      var expandToggle = function () {
        expanded = !expanded;
        if (expanded) {
          // 惰性展开：全文分片渲染（块够大，节点数可控）
          preview.textContent = '';
          for (var i = 0; i < text.length; i += STRING_CHUNK) {
            preview.appendChild(document.createTextNode(text.slice(i, i + STRING_CHUNK)));
          }
          var less = el('span', 'jf-str-more');
          less.textContent = ' … (点击收起)';
          preview.appendChild(less);
        } else {
          // 收起：回到预览态
          preview.textContent = '';
          preview.appendChild(document.createTextNode(text.slice(0, STRING_PREVIEW)));
          var m2 = el('span', 'jf-str-more');
          m2.textContent = '… (' + text.length.toLocaleString('zh-CN') + ' 字符，点击展开)';
          m2.title = '点击展开完整内容';
          preview.appendChild(m2);
        }
      };
      more.addEventListener('click', function (e) { e.stopPropagation(); expandToggle(); });
      preview.addEventListener('click', function (e) {
        // 点击「收起」标记时折叠
        if (expanded && e.target.classList && e.target.classList.contains('jf-str-more')) {
          e.stopPropagation(); expandToggle();
        }
      });
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
      span.textContent = keyText(keyNode);
      var fullPath = path || keyNode.value;
      span.title = '点击复制路径：' + fullPath;
      span.addEventListener('click', function (e) {
        e.stopPropagation();
        doCopy(fullPath, '已复制路径：' + fullPath);
      });
      return span;
    }

    /**
     * 压缩显示已改为纯 CSS 方案（body.jf-compact + .jf-compact 系列规则），
     * 不再需要独立的渲染函数：树形 DOM 结构与美化模式完全一致，
     * 只是用 CSS 把嵌套缩进/换行/折叠标记塌缩成单行。这样大 JSON 点「压缩」
     * 只是切换一个 class，几十万节点零重建、零卡顿。
     * （原 renderCompactNode / renderCompactChild 已删除）
     */
    /** 取消尚未执行的续建定时器 */
    function cancelFill() {
      if (session.timer) { clearTimeout(session.timer); session.timer = null; }
    }

    /** 给一行赋行号（按文档序递增）。numbering=false 或未开行号时跳过 */
    function numberRow(row) {
      if (!session.numbering || !opts.lineNumbers) return;
      row.firstChild.textContent = String(++session.lines);
    }

    /**
     * 建一个节点：容器 = 开行 + 子容器 + 闭行；叶子/空容器 = 单行。
     * 容器展开时把「待填充帧」压栈而不是递归填满，这是能分帧的关键。
     */
    function pushNode(parentEl, node, keyNode, isLast, path, depth) {
      depth = depth || 0;
      var isContainer = node.type === 'object' || node.type === 'array';
      var childCount = isContainer
        ? (node.type === 'object' ? node.entries.length : node.items.length)
        : 0;

      if (isContainer && childCount > 0) {
        var open = makeRow(node, depth);
        numberRow(open);
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

        var frame = null;
        if (node.expanded) {
          // entries 排序结果缓存在帧上，避免逐子节点重复 sort
          frame = { kidsEl: kids, node: node, path: path, depth: depth + 1,
                    i: 0, total: childCount,
                    entries: node.type === 'object' ? orderedEntries(node) : null,
                    closeGut: null, moreRow: null };
          session.stack.push(frame);
        } else {
          kids.classList.add('jf-children-collapsed');
        }

        var closeRow = makeRow(node, depth);
        var closeContent = el('span', 'jf-content');
        closeContent.appendChild(el('span', 'jf-punct', node.type === 'object' ? '}' : ']'));
        if (!isLast) closeContent.appendChild(el('span', 'jf-punct', ','));
        closeRow.appendChild(closeContent);
        parentEl.appendChild(closeRow);
        // 闭行的行号要等整个子树建完才连续：挂到帧上、出栈时赋号；
        // 折叠容器没有子树，当场赋号
        if (frame) frame.closeGut = closeRow.firstChild;
        else numberRow(closeRow);

        function toggleNode() {
          flushFill();                       // 上一轮渐进渲染没建完就先收尾
          node.expanded = !node.expanded;
          setToggleIcon(toggle, node.expanded);
          sum.style.display = node.expanded ? 'none' : '';
          kids.classList.toggle('jf-children-collapsed', !node.expanded);
          if (node.expanded) {
            // 展开是用户主动动作：同步建这一层（超出 MAX_CHUNK 走哨兵 + 续建）。
            // 行号由 renumber() 统一算，不能用会话计数器（插入点在文档中部）。
            session.numbering = false;
            session.total = TOTAL_ROWS;
            session.budget = MAX_CHUNK;
            session.stack.push({
              kidsEl: kids, node: node, path: path, depth: depth + 1,
              i: 0, total: childCount,
              entries: node.type === 'object' ? orderedEntries(node) : null,
              closeGut: null, moreRow: null
            });
            step();
          } else {
            renumber();
          }
          updateStats();
        }
        toggle.addEventListener('click', toggleNode);
        sum.addEventListener('click', toggleNode);
        return;
      }

      // 基本类型，或空对象 / 空数组
      var row = makeRow(node, depth);
      numberRow(row);
      var rowContent = el('span', 'jf-content');
      if (keyNode) {
        rowContent.appendChild(makeKeySpan(keyNode, path));
        rowContent.appendChild(el('span', 'jf-punct', ': '));
      }
      if (isContainer) {
        rowContent.appendChild(el('span', 'jf-punct', node.type === 'object' ? '{}' : '[]'));
      } else {
        var v = el('span', nodeValueClass(node));
        appendValueText(v, node);
        v.title = '点击复制值';
        v.style.cursor = 'pointer';
        v.addEventListener('click', function () { doCopy(valueText(node), '已复制值'); });
        rowContent.appendChild(v);
      }
      if (!isLast) rowContent.appendChild(el('span', 'jf-punct', ','));
      row.appendChild(rowContent);
      parentEl.appendChild(row);
    }

    /**
     * 消费任务栈，直到栈空或本帧预算用完。
     * 深度优先的建行顺序 === 文档顺序，所以行号可以在建行时直接递增赋值；
     * 唯一的例外是容器闭行——它的行号要等子树建完才连续，因此挂到帧上、
     * 出栈时再赋。这使得「分帧补齐」过程中行号始终是正确的。
     */
    function step() {
      while (session.stack.length) {
        var f = session.stack[session.stack.length - 1];
        // 先收尾已建完的容器：这样走到下面两个预算分支时，栈顶一定是
        // 还有子节点没建的容器，「挂哨兵」才有意义。
        // （否则会出现：总量刚好用完时栈顶已建完 → attachMore 无事可做 →
        //   这帧直接 return，帧既不出栈、闭行行号也永远欠着，渲染卡在半途。）
        if (f.i >= f.total) {
          session.stack.pop();
          if (f.moreRow && f.moreRow.parentNode) f.kidsEl.removeChild(f.moreRow);
          if (f.closeGut) {
            if (session.numbering && opts.lineNumbers) {
              f.closeGut.textContent = String(++session.lines);
            }
            f.closeGut = null;
          }
          continue;
        }
        if (session.total <= 0) {            // 总行数到顶：挂哨兵，等用户点「加载更多」
          attachMore();
          // 前沿的一串闭括号行一直没等到行号（它们的行号取决于未加载的子树），
          // 这是个用户会盯着看的稳定状态，做一次全树重编号让行号连续
          if (opts.lineNumbers) renumber();
          return;
        }
        if (session.budget <= 0) {           // 本帧建满了：挂哨兵，约下帧继续
          attachMore();
          scheduleFill();
          return;
        }
        if (f.moreRow) {                     // 续建前先摘掉哨兵，保证新行插在它前面
          if (f.moreRow.parentNode) f.kidsEl.removeChild(f.moreRow);
          f.moreRow = null;
        }
        session.budget--;
        session.total--;
        var isLast = f.i === f.total - 1;
        if (f.entries) {
          var en = f.entries[f.i];
          pushNode(f.kidsEl, en.value, en.keyNode, isLast,
                   parser.joinKey(f.path, en.keyNode.value), f.depth);
        } else {
          pushNode(f.kidsEl, f.node.items[f.i], null, isLast,
                   f.path + '[' + f.i + ']', f.depth);
        }
        f.i++;
      }
      // 栈空 = 本轮渲染全部建完
      if (!session.numbering && opts.lineNumbers) renumber();
    }

    /** 在当前栈顶容器的末尾挂「还有 N 项」哨兵（不占行号） */
    function attachMore() {
      var f = session.stack[session.stack.length - 1];
      if (!f || f.moreRow || f.i >= f.total) return;
      var remain = f.total - f.i;
      var row = el('div', 'jf-row');
      row.style.setProperty('--jf-depth', String(f.depth));
      if (session.late) row.classList.add('jf-late');
      var gut = el('span', 'jf-no jf-no-more');
      if (!opts.lineNumbers) gut.style.display = 'none';
      row.appendChild(gut);
      // 哨兵不占行号：它会在续建时被移除，占了号就会留下一个永久的号洞
      var ct = el('span', 'jf-content');
      var s = el('span', 'jf-summary',
        '… 还有 ' + remain.toLocaleString() + ' 项，点击加载更多');
      s.title = '点击继续加载';
      s.addEventListener('click', function () {
        cancelFill();
        session.numbering = false;           // 插入点在文档中部，交给 renumber()
        session.total = TOTAL_ROWS;          // 用户主动要更多，重新给足总量
        session.budget = MAX_CHUNK * 2;
        step();
      });
      ct.appendChild(s);
      row.appendChild(ct);
      f.kidsEl.appendChild(row);
      f.moreRow = row;
    }

    /** 把没建完的行一次性同步建完（展开/加载更多前调用，罕见路径） */
    function flushFill() {
      cancelFill();
      if (!session.stack.length) return;
      session.budget = Infinity;
      session.total = Infinity;
      step();
    }

    /** 约下一帧继续建（setTimeout(0) 让浏览器先上屏、响应输入） */
    function scheduleFill() {
      if (session.timer) return;
      var token = renderToken;
      session.timer = setTimeout(function () {
        session.timer = null;
        if (token !== renderToken) return;   // 期间发起了新的格式化，这轮作废
        session.budget = FILL_ROWS;
        session.late = true;
        step();
      }, 0);
    }

    function renumber() {
      var gutt = body.querySelectorAll('.jf-no');
      var k = 0;
      for (var i = 0; i < gutt.length; i++) {
        if (gutt[i].classList.contains('jf-no-more')) continue;  // 哨兵是占位符，不编号
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
          afterParse(res);
        } catch (e) {
          toast('宽松解析仍然失败');
        }
      });
      box.appendChild(retry);
      body.appendChild(box);
    }

    function render() {
      cancelFill();
      renderToken++;
      body.textContent = '';
      body.scrollTop = 0;
      // 压缩模式只靠 CSS class 切换排版（.jf-compact），不改变树形 DOM 结构
      body.classList.toggle('jf-compact', state.outMode === 'compact');
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
      /* 首帧只建 PAINT_ROWS 行就交给浏览器上屏（肉眼看是即时的），
         剩下的行由 scheduleFill 分帧补齐。过去是一次建完 5700 行再布局，
         样式重算 + 布局近 500ms 全部堵在主线程上。 */
      session.stack.length = 0;
      session.lines = 0;
      session.numbering = true;
      session.late = false;
      session.budget = PAINT_ROWS;
      session.total = TOTAL_ROWS;
      var frag = body.ownerDocument.createDocumentFragment();
      pushNode(frag, state.root, null, true, '$', 0);
      body.appendChild(frag);
      session.late = true;
      step();                                // 用掉剩余的首帧预算，不够则自动约下帧
      updateStats();
    }

    /* ---------------- 折叠控制 ---------------- */
    function setAllExpanded(expanded) {
      if (!state.root) return;
      /* 不能直接 parser.walk 后逐个改：大 JSON 走的是惰性树，walk 会把整棵树
         物化出来（20MB 约 32 万节点、几百毫秒）。交给解析器的快捷实现：
         翻转默认态 + 只改已物化出来的容器。 */
      parser.setAllExpanded(state.root, expanded);
      render();
    }


    /* ---------------- 路径 ---------------- */
    function setPath(p) {
      state.currentPath = p || '';
      pathLabel.textContent = '';
      if (!p) return;
      pathLabel.appendChild(document.createTextNode('路径 '));
      pathLabel.appendChild(el('b', null, p));
    }

    /* ---------------- 输出 ---------------- */
    /**
     * 惰性树（大文件走原生解析）输出快捷路径。
     *
     * 树里的值从未被改写，规范化的原生序列化结果与逐节点 compact()/pretty()
     * 完全一致——两侧的取值同源（数字都是 String(value)、字符串都是
     * JSON.stringify，raw 也是这么还原的）。但省掉了把 60 万个节点
     * 全部物化出来的开销：20MB 的复制/导出从近一秒降到约 100ms。
     *
     * 「按键排序」会改变顺序，退回逐节点实现；缩进单位超过 10 字符时
     * JSON.stringify 会自行截断，也退回，保证输出与逐节点实现逐字节相同。
     */
    function nativeText(node, unit) {
      if (!node.__sess || opts.sortKeys) return null;
      if (unit && unit.length > 10) return null;
      return unit ? JSON.stringify(node.__n, null, unit) : JSON.stringify(node.__n);
    }

    function compact(node) {
      var whole = nativeText(node, null);
      if (whole !== null) return whole;
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
      var whole = nativeText(node, unit);
      if (whole !== null) return whole;
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

    /**
     * 输出文本。结果按「模式+缩进+树版本」缓存：
     * 旧版 updateStats() 每次渲染/折叠都调用这里，把整棵树序列化成
     * 10MB 级字符串只为显示一个"输出多大"，是大 JSON 卡死的元凶之一。
     */
    var treeVersion = 0;
    function outputText() {
      if (!state.root) return state.text || '';
      var key = state.outMode + ':' + opts.indent + ':' + treeVersion;
      if (outCache.key === key) return outCache.text;
      var t;
      if (state.outMode === 'compact') t = compact(state.root);
      else t = pretty(state.root, NS.indentUnit(opts.indent), 0);
      outCache.key = key;
      outCache.text = t;
      return t;
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
      // 输出体积需要全树序列化（pretty/compact），对十几 MB 的 JSON 是数百毫秒的
      // 同步开销。这里绝不主动触发序列化——只在缓存已命中（用户点过复制/导出）
      // 时才顺带展示，把序列化完全移出「粘贴 → 首屏渲染」的关键路径。
      var key = state.outMode + ':' + opts.indent + ':' + treeVersion;
      var outPart = (outCache.key === key && outCache.text)
        ? ' · 输出 ' + formatBytes(outCache.text.length)
        : '';
      statsLabel.textContent =
        state.stats.count + ' 个节点 · 深度 ' + state.stats.depth +
        ' · 源码 ' + formatBytes(state.text.length) + outPart;
    }

    function afterParse(res) {
      /* 解析器在解析途中就统计好节点数/深度，并把「默认展开」一次定好，
         所以这里不再 stats() + setAllExpanded() 两趟全树遍历。
         11MB 文档有上百万个节点，那两趟遍历是每次格式化都要付的固定成本。
         res.count 缺失时才回退到老路径（兼容外部只替换了部分文件的场景）。
         注意：老路径的 setAllExpanded 内部会顺带 render()，新路径必须显式 render。 */
      if (res && typeof res.count === 'number') {
        state.stats = { count: res.count, depth: res.depth };
        render();
      } else {
        state.stats = parser.stats(state.root);
        setAllExpanded(true);
      }
      setPath('');
    }

    /* ---------------- 对外接口 ---------------- */
    function setText(text, options) {
      options = options || {};
      state.text = typeof text === 'string' ? text : String(text == null ? '' : text);
      state.error = null;
      state.root = null;
      state.lenient = false;
      outCache.key = null;
      treeVersion++;
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
      afterParse(res);
      return true;
    }

    function updateOptions(patch) {
      Object.assign(opts, patch || {});
      // sortKeys 等影响输出内容的选项变化时，输出缓存必须失效
      outCache.key = null;
      applyTheme();
      applyFont();
      syncToolbar();
      if (state.root) {
        render();
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
