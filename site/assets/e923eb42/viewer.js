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
   * 虚拟化渲染参数（大 JSON 高性能的核心）。
   *
   * 树视图原来是「一个节点一行真实 DOM」：22MB 文档 = 36 万行 DOM，浏览器必崩
   * ——这正是以前必须有 TOTAL_ROWS = 6000 上限、以及「超过 600KB 就切大文档
   * 视图」的原因（拿砍行数来保命）。
   *
   * 现在换成业界一致的做法（Dadroit / JSON Hero / svelte-jsoneditor 同思路）：
   * 把树摊平成一张**可见行表**（content/rowmodel.js），用一个 spacer 撑出总高度，
   * 只把视口内的那几十行挂成 DOM。于是 DOM 行数与文档大小无关，折叠/展开只影响
   * 行表长度与 spacer 高度，**不再需要任何行数上限**。
   *
   * 代价（明确记下来，不是遗漏）：
   *  - 行高固定：长值不再自动折行，超出部分裁掉，全文靠悬停提示 + 点击复制；
   *  - 跨行框选复制做不到（虚拟化列表的固有代价）；
   *    复制走「点键复制路径 / 点值复制值 / 工具条复制整份」三条路。
   */
  /** 视口上下各多渲染几行，滚动时不至于露白 */
  var OVERSCAN = 6;
  /** 单行里最多渲染多少个字符，超出的部分靠悬停提示 + 点击复制拿全文 */
  var VALUE_MAX = 512;
  /** 「压缩」视图最多渲染多少字符（一整行几 MB 的文本，浏览器 shaping 会假死） */
  var COMPACT_MAX = 2 * 1024 * 1024;
  /** 视口上下留白，与旧版 .jf-body 的 padding 保持一致 */
  var PAD_TOP = 14;
  var PAD_BOTTOM = 80;

  /* ------------------------------------------------------------------ *
   * 样式
   * ------------------------------------------------------------------ */
  /**
   * 配色 token 单独成串：既挂到树视图的 .jf-root，也挂到大文档视图的 .jf-big。
   * 两者必须共用同一份定义——不然改了一处、另一处配色就分叉了
   * （bigview.js 的 CodeMirror 主题正是按这些变量上色的）。
   */
  var TOKEN_LIGHT = [
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
  ].join('\n');

  var TOKEN_DARK = [
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
  ].join('\n');

  var VIEWER_CSS = [
    '.jf-root{all:initial;}',
    '.jf-root{',
    TOKEN_LIGHT,
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
    TOKEN_DARK,
    '}',

    /* 大文档视图（CodeMirror）宿主：不套 .jf-root 的 all:initial，
       只借同一套 token，外加必须的尺寸与等宽字体 */
    '.jf-big{',
    TOKEN_LIGHT,
    '  position:relative;display:block;height:100%;width:100%;overflow:hidden;',
    '  background:var(--jf-bg);color:var(--jf-text);',
    '  font-family:' + MONO_FONT + ';',
    '  font-size:' + DEFAULT_FONT_SIZE + 'px;',
    '  box-sizing:border-box;',
    '}',
    '.jf-big *,.jf-big *::before,.jf-big *::after{box-sizing:border-box;}',
    '.jf-big[data-theme="dark"]{',
    TOKEN_DARK,
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


    /* ---------------- 正文（虚拟化：spacer + 视口窗口） ---------------- */
    '.jf-body{flex:1 1 auto;overflow-y:auto;overflow-x:hidden;background:var(--jf-bg);',
    '  position:relative;}',
    '.jf-body::-webkit-scrollbar{width:13px;height:13px;}',
    '.jf-body::-webkit-scrollbar-thumb{background:#d4d8dd;border:3px solid var(--jf-bg);border-radius:8px;}',
    '.jf-body::-webkit-scrollbar-thumb:hover{background:#bcc2c9;}',
    '.jf-root[data-theme="dark"] .jf-body::-webkit-scrollbar-thumb{background:#39404a;}',

    /* 撑高元素：高度 = 上下留白 + 行数 × 行高，决定滚动条长度；
       窗口用 absolute + translateY 定位到视口那一段 —— 滚动只改 transform 与
       窗口内容，spacer 高度不变，所以滚动条不会抖。 */
    '.jf-sizer{position:relative;width:100%;}',
    '.jf-window{position:absolute;top:0;left:0;right:0;padding:0 18px;}',

    /* 一行 = 定高 + 不换行 + 溢出裁掉。
       定高是虚拟化的前提：「第 i 行在哪儿、spacer 该多高」全靠行高算出来。
       代价是长值不再自动折行，超出部分裁掉，全文交给悬停提示与点击复制。 */
    '.jf-row{display:flex;align-items:flex-start;height:var(--jf-lh);',
    '  line-height:var(--jf-lh);white-space:nowrap;overflow:hidden;border-radius:4px;',
    '  padding-left:calc(3px + var(--jf-depth,0) * (var(--jf-indent) + 3px));',
    '  padding-right:3px;',
    /* 层级引导线：扁平行表没有嵌套容器可挂 border-left 了，改用一条
       repeating-linear-gradient + background-size 裁剪：线在 2px、21px、40px…
       （每层 19px = 缩进 16px + 间距 2px + 线宽 1px），裁剪宽度 = 层数 × 19px - 16px，
       正好把「第 层数+1 条」及之后的线挡在元素外 —— 每一行只画自己需要的引导线，
       零额外 DOM、零额外样式写入（只读 --jf-depth）。 */
    '  background-image:repeating-linear-gradient(90deg,transparent 0 2px,',
    '    var(--jf-guide) 2px 3px,transparent 3px 19px);',
    '  background-repeat:no-repeat;',
    '  background-size:max(0px,calc(var(--jf-depth,0) * (var(--jf-indent) + 3px) - 16px)) 100%;}',
    '.jf-row:hover{background-color:var(--jf-bg-hover);}',
    '.jf-no{flex:0 0 auto;width:4em;padding-right:1.1em;text-align:right;color:var(--jf-muted);',
    /* 行号用整数 px + 与正文同一个行高变量：行号不再是 .86em 这种小数尺寸
       （14×.86 = 12.04px，落在分数设备像素上会发虚），也顺带修掉了行号
       与正文行高不一致导致的逐行错位。 */
    '  opacity:.6;user-select:none;font-size:12px;line-height:var(--jf-lh);background:var(--jf-bg);',
    '  position:relative;',
    /* 行号要钉在查看器最左侧一列，不随层级往右漂。扁平行表里缩进做在行的
       padding-left 上，所以这里把 padding 那一段用 relative 偏移抵消掉：
       行内水平开销 = 3px + 层数 × 19px，偏移 -(层数 × 19px) - 3px 之后，
       任何层级的行号都落在同一个 x 上。用 relative + left 而不是负 margin：
       flex 里首项的负 margin 会把后面的内容一起拖过去，正好抵消缩进。 */
    '  left:calc(var(--jf-depth,0) * (var(--jf-indent) + 3px) * -1 - 3px);}',
    '.jf-content{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;',
    '  white-space:nowrap;}',

    /* 「压缩」视图：直接给紧凑序列化文本。
       旧版是纯 CSS 把嵌套结构塌缩成一行（DOM 不动），但虚拟化下行表里
       只有视口那几十行，塌缩出来的也只是一小段，语义上已经不成立了。 */
    '.jf-ctext{margin:0;padding:14px 18px 80px;font:inherit;color:var(--jf-text);',
    '  white-space:pre-wrap;word-break:break-all;}',
    '.jf-ctext-note{color:var(--jf-accent);font-size:12.5px;margin:14px 0 0;}',

    /* 键与括号之间的圆角方框折叠标记 */
    '.jf-toggle{display:inline-flex;align-items:center;justify-content:center;',
    '  width:15px;height:15px;margin:0 3px;padding:0;border:0;background:none;',
    '  color:var(--jf-toggle);cursor:pointer;vertical-align:-2.5px;}',
    '.jf-toggle svg{width:14px;height:14px;display:block;pointer-events:none;}',
    '.jf-toggle:hover{color:var(--jf-toggle-hover);}',

    '.jf-key{color:var(--jf-key);font-weight:600;cursor:pointer;border-radius:3px;}',
    '.jf-key:hover{background:var(--jf-key-bg,rgba(146,39,143,.09));}',
    /* 值：点一下复制。长值在行内被裁掉（见 .jf-content），全文看悬停提示 */
    '.jf-val{cursor:pointer;}',
    '.jf-str{color:var(--jf-str);}',
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
    '.jf-error{margin:16px 18px;padding:18px 20px;border:1px solid var(--jf-border);',
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

    /** 可见行表（rowmodel.js）。null 表示当前没有可渲染的树（错误卡 / 空内容 / 压缩视图） */
    var model = null;
    /** 撑高元素：高度 = 行数 × 行高，决定滚动条长度 */
    var sizerEl = null;
    /** 视口窗口：只装 [view.first, view.last) 这段行 */
    var winEl = null;
    /** 当前已经挂在 DOM 上的行区间，滚动时用它判断要不要重画 */
    var view = { first: -1, last: -1 };
    /** 行高（px）。与写进 --jf-lh 的算法同源，改字号时一起更新 */
    var ROW_H = Math.round(DEFAULT_FONT_SIZE * LINE_RATIO);
    /** 滚动合并用的 rAF 句柄 */
    var rafId = 0;
    /** 观察视口尺寸变化（窗口缩放 / 工具条换行） */
    var resObs = null;
    /** true = 现在建出来的行属于「补画」（滚动/折叠重画），不打入场动效 */
    var lateRows = false;
    /** 输出文本缓存：outputText() 的结果按「模式+缩进+树版本」缓存，避免每次统计都全树序列化 */
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

    /* 滚动只重画窗口，不重建行表；用 rAF 合并，一帧最多画一次。
       监听挂在 body 上（只挂一次），窗口里那些行元素随窗口整体换掉，
       不需要（也不能）逐行挂监听 —— 那是虚拟化列表卡顿的常见来源。 */
    body.addEventListener('scroll', scheduleWindow, { passive: true });
    body.addEventListener('click', onBodyClick);
    if (typeof ResizeObserver === 'function') {
      resObs = new ResizeObserver(function () {
        layout();
        updateWindow(true);
      });
      resObs.observe(body);
    } else if (window.addEventListener) {
      window.addEventListener('resize', function () { layout(); updateWindow(true); });
    }

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
        /* 必须重渲染。旧版这一步只切一个 CSS class（靠 CSS 把嵌套 DOM 塌缩成
           一行），虚拟化之后树里只有视口那几十行，CSS 已经表达不了「整篇压缩成
           一行」这件事了，改由 render() 换成紧凑文本视图。 */
        render();
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
      // 行高就是虚拟化的「坐标系」：字号一改，行高、spacer 高度、窗口位置全要重算
      if (model) {
        layout();
        updateWindow(true);
      }
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
     * 值文本：单行渲染，超过 VALUE_MAX 就截断。
     *
     * 旧做法是「默认折叠 + 点开再分片渲染全文」，但虚拟化的前提是**定高行**，
     * 一行里塞不下多行文本，所以那条路走不通了。更要紧的是：一个几 MB 的字符串
     * 值哪怕只是塞进一个 text node，浏览器的 shaping 也会假死——所以这里连
     * text node 都只放前 VALUE_MAX 个字符，全文留给「点击复制」和悬停提示。
     */
    function appendValueText(container, node) {
      var text = valueText(node);
      if (text.length <= VALUE_MAX) {
        container.appendChild(document.createTextNode(text));
        return;
      }
      container.appendChild(document.createTextNode(text.slice(0, VALUE_MAX) + '…'));
    }

    /** 值的悬停提示：短值只提示「点击复制」，长值顺带给出开头一截 */
    function valueTip(node) {
      var text = valueText(node);
      if (text.length <= VALUE_MAX) return '点击复制值';
      return '点击复制值（共 ' + text.length.toLocaleString('zh-CN') + ' 字符，行内已截断）\n' +
        '—— 开头 1000 字符 ——\n' + text.slice(0, 1000) + '…';
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

    /* ---------------- 渲染（虚拟化窗口） ---------------- */

    /**
     * 显示顺序下的子节点取值器。
     *
     * 「按键排序」是用户可见设置，但排序结果必须缓存：不缓存的话每次摊平
     * （首次渲染 / 每次展开 / 每次折叠重建）都要对每个对象重新 slice + sort，
     * 一个 20 万键的对象会被排上几十遍。树是不可变的（查看器不编辑 JSON），
     * 所以缓存一次就够。
     */
    function orderedEntries(node) {
      if (!opts.sortKeys) return node.entries;
      if (!node.__jfSorted) {
        node.__jfSorted = node.entries.slice().sort(function (a, b) {
          return a.keyNode.value.localeCompare(b.keyNode.value, 'zh-Hans-CN');
        });
      }
      return node.__jfSorted;
    }

    /** 行表按显示顺序摊平；不排序时 child 就是解析器的默认取值器 */
    function rowAccess() {
      if (!opts.sortKeys) return null;
      return {
        count: function (node) {
          if (node.type === 'object') return node.entries.length;
          if (node.type === 'array') return node.items.length;
          return 0;
        },
        child: function (node, i) {
          if (node.type === 'object') return orderedEntries(node)[i].value;
          return node.items[i];
        }
      };
    }

    /** 行高（px）：必须与 applyFont 写进 --jf-lh 的算法一致，否则窗口会错位 */
    function rowHeight() {
      var size = parseInt(opts.fontSize, 10);
      if (!size || size < 8) size = DEFAULT_FONT_SIZE;
      return Math.round(size * LINE_RATIO);
    }

    function isContainerNode(n) {
      return n.type === 'object' || n.type === 'array';
    }

    /** 容器子节点个数（惰性 Proxy 的 length 是 O(1)，不会物化任何子节点） */
    function childCountOf(n) {
      if (n.type === 'object') return n.entries.length;
      if (n.type === 'array') return n.items.length;
      return 0;
    }

    /**
     * 按行表长度铺开高度。
     * 字号、行数、视口宽度任何一项变了都要走这里（sizer 高度决定滚动条长度）。
     */
    function layout() {
      ROW_H = rowHeight();
      if (!sizerEl || !model) return;
      sizerEl.style.height =
        (PAD_TOP + model.length * ROW_H + PAD_BOTTOM) + 'px';
    }

    /** 造一行 DOM。i = 行表下标（也是文档序行号 - 1） */
    function buildRow(i) {
      var node = model.nodeAt(i);
      var close = model.isClose(i);
      var row = el('div', 'jf-row');
      row.setAttribute('data-i', String(i));
      row.setAttribute('data-jf-node', String(node.id));
      /* 首屏之后才建的行（滚动补画、折叠重画）不打入场动效的标记：
         editor.css 里 .is-fresh 期间 rowIn 是 0.42s 的浮现，滚动时每帧换一批
         行元素会变成整屏持续闪入 —— 这正是 jf-late 存在的意义。 */
      if (lateRows) row.classList.add('jf-late');
      /* 缩进、行号位置、层级引导线全部由这一个变量驱动（见 CSS 的 .jf-row） */
      row.style.setProperty('--jf-depth', String(node.depth || 0));

      var gut = el('span', 'jf-no');
      if (opts.lineNumbers) gut.textContent = String(i + 1);
      else gut.style.display = 'none';
      row.appendChild(gut);

      var content = el('span', 'jf-content');
      if (close) {
        /* 闭行：`}` / `]`，末项后面要补逗号 */
        content.appendChild(el('span', 'jf-punct', node.type === 'object' ? '}' : ']'));
        if (!model.isLast(i)) content.appendChild(el('span', 'jf-punct', ','));
      } else if (isContainerNode(node) && childCountOf(node) > 0) {
        /* 非空容器开行：键 + 折叠标记 + 开括号（折叠时再补一段摘要） */
        appendKey(content, node);
        content.appendChild(makeToggle(node.expanded));
        content.appendChild(el('span', 'jf-punct', node.type === 'object' ? '{' : '['));
        if (!node.expanded) {
          var sum = el('span', 'jf-summary', summaryText(node));
          sum.title = '点击展开';
          content.appendChild(sum);
        }
      } else {
        /* 叶子，或空容器 */
        appendKey(content, node);
        if (isContainerNode(node)) {
          content.appendChild(el('span', 'jf-punct', node.type === 'object' ? '{}' : '[]'));
        } else {
          var v = el('span', 'jf-val ' + nodeValueClass(node));
          appendValueText(v, node);
          v.title = valueTip(node);
          content.appendChild(v);
        }
        if (!model.isLast(i)) content.appendChild(el('span', 'jf-punct', ','));
      }
      row.appendChild(content);
      return row;
    }

    /** 键 + 冒号。键的 title 是该节点的完整路径，点一下复制 */
    function appendKey(content, node) {
      if (!node.keyNode) return;
      var span = el('span', 'jf-key');
      span.textContent = keyText(node.keyNode);
      span.title = '点击复制路径：' + model.pathOf(node);
      content.appendChild(span);
      content.appendChild(el('span', 'jf-punct', ': '));
    }

    function makeToggle(expanded) {
      var b = el('button', 'jf-toggle');
      b.type = 'button';
      b.title = expanded ? '折叠' : '展开';
      b.appendChild(toggleGlyph(expanded));
      return b;
    }

    /** 取消待执行的窗口重画 */
    function cancelWindow() {
      if (rafId) {
        if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(rafId);
        rafId = 0;
      }
    }

    /**
     * 重画视口窗口：把 [first, last) 这段行挂成 DOM，整段用 translateY 定位。
     *
     * 滚动只改 translateY 与窗口内容，spacer 高度不动 —— 所以滚动条长度稳定、
     * 不会边滚边抖。窗口上下各多画 OVERSCAN 行，快速滚动时不会露白。
     */
    function updateWindow(force) {
      if (!model || !winEl) return;
      var vh = body.clientHeight || 0;
      if (vh <= 0) vh = 600;                    // 还没量到尺寸时按一屏给个合理值
      var first = Math.floor(body.scrollTop / ROW_H) - OVERSCAN;
      if (first < 0) first = 0;
      var last = first + Math.ceil(vh / ROW_H) + OVERSCAN * 2 + 1;
      if (last > model.length) last = model.length;
      if (!force && first === view.first && last === view.last) return;
      view.first = first;
      view.last = last;
      winEl.style.transform = 'translateY(' + (PAD_TOP + first * ROW_H) + 'px)';
      var frag = body.ownerDocument.createDocumentFragment();
      for (var i = first; i < last; i++) frag.appendChild(buildRow(i));
      winEl.textContent = '';
      winEl.appendChild(frag);
    }

    /** 滚动 / 尺寸变化都走这里：一帧最多重画一次 */
    function scheduleWindow() {
      if (rafId) return;
      if (typeof requestAnimationFrame !== 'function') { updateWindow(false); return; }
      rafId = requestAnimationFrame(function () {
        rafId = 0;
        updateWindow(false);
      });
    }

    /**
     * 把行表第 index 行滚进视口，返回落定后的首行下标（无效返回 -1）。
     *
     * 虚拟化之后，「让某一行出现在屏幕上」这件事只有本模块做得到 —— DOM 里
     * 压根没有那一行，外部再怎么 querySelector 都找不到。所以路径跳转、
     * 搜索结果定位、编辑器侧的「跳到某个节点」都得走这个入口。
     *
     * 目标行放在视口上方约 1/3 处，上下留出上下文；两端做钳制，免得露出留白。
     * 同步重画一次（不等 rAF），这样调用方紧接着就能量到正确结果。
     */
    function revealRow(index) {
      if (!model || !winEl) return -1;
      var n = model.length;
      if (n <= 0) return -1;
      var i = index < 0 ? 0 : (index > n - 1 ? n - 1 : index);
      var h = body.clientHeight || 0;
      var want = i * ROW_H - Math.round(h / 3);
      if (want < 0) want = 0;
      var max = body.scrollHeight - h;
      if (max > 0 && want > max) want = max;
      body.scrollTop = want;
      updateWindow(true);
      // 行表可能因为目标行落在窗口之外而重新对齐，返回实际首行下标
      return view.first;
    }

    /**
     * 事件委托：整棵树只挂一个 click。
     *
     * 虚拟化下窗口里的行元素每滚一帧就整批换掉，逐行挂监听意味着每帧都要建
     * 一批闭包、再回收一批 —— 那是列表滚动卡顿的常见来源。这里改成从行号的
     * data-i 反查节点，监听只在创建时挂一次。
     */
    function onBodyClick(e) {
      var t = e.target;
      if (!t || !t.closest || !winEl || !model) return;
      var rowEl = t.closest('.jf-row');
      if (!rowEl || !winEl.contains(rowEl)) return;
      var i = parseInt(rowEl.getAttribute('data-i'), 10);
      if (isNaN(i)) return;
      var node = model.nodeAt(i);
      if (!node) return;

      if (t.closest('.jf-toggle') || t.closest('.jf-summary')) {
        /* 折叠 / 展开：只动行表的一段（O(插入行数)），然后把窗口重画一遍。
           spacer 高度跟着 model.length 变，滚动位置保持不变 —— 被点的这一行
           在它之前的位置没有变，所以视觉上它「钉在原地」收放。 */
        if (model.isClose(i) || !isContainerNode(node)) return;
        model.setExpanded(node, !node.expanded, i);
        layout();
        updateWindow(true);
        updateStats();
        return;
      }
      if (t.closest('.jf-key')) {
        var p = model.pathOf(node);
        doCopy(p, '已复制路径：' + p);
        return;
      }
      if (t.closest('.jf-val')) doCopy(valueText(node), '已复制值');
    }

    /**
     * 「压缩」视图：直接给紧凑序列化文本。
     *
     * 旧版是纯 CSS 把嵌套结构塌缩成一行（DOM 不动），但扁平行表里只挂着视口
     * 那几十行，塌缩出来的也只是文档的一小段，语义上已经不成立了。序列化走
     * nativeText 快路径（原生 JSON.stringify），20MB 也就百来毫秒。
     *
     * 超过 COMPACT_MAX 只渲染前面一段：一整行几 MB 的文本连 shaping 都会假死，
     * 而完整内容本来就能用「复制 / 下载」拿到，没必要在屏幕上赌一把。
     */
    function renderCompactText() {
      var text = outputText();
      var shown = text.length > COMPACT_MAX ? text.slice(0, COMPACT_MAX) : text;
      var box = el('pre', 'jf-ctext');
      // 分块塞文本节点：单个几 MB 的 text node 会拖慢选区与后续操作
      for (var i = 0; i < shown.length; i += 65536) {
        box.appendChild(body.ownerDocument.createTextNode(shown.slice(i, i + 65536)));
      }
      if (shown.length < text.length) {
        box.appendChild(el('div', 'jf-ctext-note',
          '… 仅显示前 ' + formatBytes(COMPACT_MAX) + '（共 ' + formatBytes(text.length) +
          '），完整内容请用「复制」或「下载」'));
        /* 上面那份完整文本可能是几十 MB 的字符串（JS 字符串 2 字节/字符，
           20MB 文本就是 40MB 内存）。既然屏幕上只显示前一段，就别让缓存一直
           占着它 —— 真要复制/下载时再序列化一次就是了。 */
        outCache.key = null;
        outCache.text = '';
      }
      body.appendChild(box);
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
      cancelWindow();
      body.textContent = '';
      // body 上的 jf-compact 只是「当前是压缩视图」的状态标记（CSS 不再依赖它）
      body.classList.toggle('jf-compact', state.outMode === 'compact');
      model = null;
      sizerEl = null;
      winEl = null;
      view.first = view.last = -1;
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
      if (state.outMode === 'compact') {
        renderCompactText();
        updateStats();
        return;
      }
      /* 建行表 → 铺 spacer 高度 → 画视口那几十行。
         行表只摊平「当前可见」的行：折叠的分支不进表、也不物化它的后代。
         整棵树全展开时行表是 O(节点数)（22MB 约 36 万行、实测 ~280ms），
         那是文档规模决定的下限成本，与「渲染」无关 —— 渲染始终只有几十行。 */
      model = NS.rowModel.create(state.root, rowAccess());
      sizerEl = el('div', 'jf-sizer');
      winEl = el('div', 'jf-window');
      sizerEl.appendChild(winEl);
      body.appendChild(sizerEl);
      body.scrollTop = 0;
      layout();
      lateRows = false;                      // 首屏这一批行要播入场动效
      updateWindow(true);
      lateRows = true;                       // 之后的滚动补画都不再播
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
      /* 行数（行表长度）是虚拟化后最该让用户知道的数字：文档多大都只有几十行
         挂在 DOM 上，真正决定滚动条长度的是行表长度。压缩视图没有行表，不显示。 */
      var rowsPart = model ? model.length.toLocaleString('zh-CN') + ' 行 · ' : '';
      statsLabel.textContent =
        rowsPart + state.stats.count + ' 个节点 · 深度 ' + state.stats.depth +
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
      cancelWindow();
      if (toastTimer) clearTimeout(toastTimer);
      if (resObs) { try { resObs.disconnect(); } catch (e) { /* ignore */ } resObs = null; }
      if (rootEl && rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
    }

    return {
      setText: setText,
      updateOptions: updateOptions,
      destroy: destroy,
      outputText: outputText,
      /** 把行表第 index 行滚进视口（虚拟化后唯一的「显示某一行」入口） */
      revealRow: revealRow,
      toast: toast,
      getState: function () { return state; },
      /** 调试/验收用：虚拟化窗口的当前状态（不参与渲染逻辑） */
      getView: function () {
        return {
          rows: model ? model.length : 0,
          first: view.first,
          last: view.last,
          dom: winEl ? winEl.children.length : 0,
          rowHeight: ROW_H
        };
      },
      rootEl: rootEl
    };
  }

  NS.createViewer = createViewer;

  /**
   * 确保查看器样式表（含 --jf-* 配色 token）已注入到 el 所在文档 / ShadowRoot。
   * 大文档视图（bigview.js）没有树视图实例可依附，得自己保证 token 可用——
   * 否则 CodeMirror 主题里那些 var(--jf-bg) 全部取不到值，配色会整片丢掉。
   */
  NS.installViewerStyles = installStyles;
  NS.VIEWER_CSS = VIEWER_CSS;
})();
