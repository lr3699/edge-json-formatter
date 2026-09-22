/**
 * 「粘贴 JSON 格式化」独立页。
 *
 * 定位：扩展原本只能格式化「网页上的 JSON」，用户从聊天记录、日志、终端里
 * 复制出来的 JSON 没有地方贴。本页补上这条入口。
 *
 * 复用 src/content/viewer.js（该模块不依赖任何 chrome.* API），
 * 本文件只负责：输入 → 防抖 → 解析 → 渲染 → 动效 → 设置同步。
 */
(function () {
  'use strict';

  var NS = globalThis.__EDGE_JSON_FORMATTER__;
  if (!NS || !NS.createViewer) return;

  /**
   * 是否运行在扩展环境里。
   * 本页同时支持「直接在普通浏览器里打开」——方便调样式、也方便不装扩展先看效果，
   * 所以所有 chrome.* 调用都要先过这道判断（viewer.js / json-parser.js 本身不碰 chrome）。
   */
  var HAS_EXT = typeof chrome !== 'undefined' &&
    !!chrome.runtime && !!chrome.runtime.id;

  var $ = function (id) { return document.getElementById(id); };

  var inputEl = $('input');
  var rawViewEl = $('rawView');
  var rawSizerEl = $('rawSizer');
  var rawContentEl = $('rawContent');
  var viewerHost = $('viewer');
  var welcomeEl = $('welcome');
  var statsEl = $('stats');
  var fileInfoEl = $('fileInfo');
  var msgEl = $('msg');
  var pillEl = $('statusPill');
  var pillTextEl = $('pillText');
  var panelInput = $('panelInput');
  var splitterEl = $('splitter');

  /** 输入变化后自动格式化的防抖间隔 */
  var DEBOUNCE_MS = 220;

  /**
   * 大输入阈值（字符数）。超过此值的文本不再写回 <textarea> ——
   * 浏览器对超长文本节点做布局/绘制会阻塞主线程数秒（粘贴 11MB JSON 实测
   * textarea 重排 + 同步格式化叠加导致 7~11 秒无响应），这是「Ctrl+V 卡顿很久」
   * 的真正根因。改用「内存文本源 + 虚拟滚动只读原文视图」：原文完整可见、逐行可查，
   * 但只渲染可视区域，20MB 内也不卡；格式化结果照常进右侧树（查看器已分批渲染）。
   */
  var BIG_INPUT_THRESHOLD = 512 * 1024; // 512 KB

  /* ---------------- 入场动效参数 ---------------- */

  /** 最多对前多少行做错落延迟；更多的行在首屏之外，没必要等 */
  var STAGGER_ROWS = 40;
  /** 相邻两行的延迟（ms） */
  var STAGGER_STEP = 11;
  /** 单行动画时长（ms），需与 CSS 中 rowIn 的时长保持一致 */
  var ROW_DURATION = 420;

  var SAMPLE = [
    '{',
    '  "code": "0",',
    '  "msg": "success",',
    '  "data": {',
    '    "orderId": "600653836507516928",',
    '    "amount": 128.5,',
    '    "paid": true,',
    '    "refunded": null,',
    '    "tags": ["vip", "2026-09"],',
    '    "buyer": {',
    '      "id": 10086,',
    '      "nickname": "张三",',
    '      "remark": "带\\"引号\\"、制表符\\\\t 和换行的备注"',
    '    },',
    '    "items": [',
    '      { "sku": "A-1", "name": "机械键盘", "qty": 1, "price": 399 },',
    '      { "sku": "B-2", "name": "显示器支架", "qty": 2, "price": 89 }',
    '    ]',
    '  },',
    '  "ts": 1784173433013',
    '}'
  ].join('\n');

  var settings = Object.assign({}, NS.DEFAULTS);
  var viewer = null;
  var debounceTimer = null;
  var animTimer = null;
  var lastRendered = null;
  /** 内存文本源：小输入与 textarea 同步；大输入只存这里，不写回 textarea */
  var sourceText = '';
  /** 本次输入事件的来源，决定要不要播放入场动效：'paste' | 'drop' | 'typing' */
  var inputKind = 'typing';

  /* ---------------- 状态显示 ---------------- */

  function setPill(kind, text) {
    pillEl.className = 'pill' + (kind ? ' ' + kind : '');
    pillTextEl.textContent = text;
  }

  function setMessage(text, kind) {
    msgEl.textContent = text || '';
    msgEl.className = 'msg' + (kind ? ' ' + kind : '');
    // 大文档模式会把完整说明挂在 title 上；换了文案就清掉，免得残留旧提示
    msgEl.title = '';
  }

  function formatBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function updateStats() {
    var chars = sourceText.length;
    if (!chars) {
      statsEl.textContent = '0 字符';
      return;
    }
    statsEl.textContent = chars.toLocaleString('zh-CN') + ' 字符 · ' + formatBytes(chars);
  }

  /* ---------------- 大输入：虚拟滚动只读原文视图 ---------------- */

  /** 原文视图行高（px），需与 editor.css 中 .raw-line 的 height/line-height 一致 */
  var RAW_LINE_H = 24;
  /** 每行在 sourceText 里的起始偏移；rawLineOffsets[i] 是第 i 行的起点 */
  var rawLineOffsets = [];
  var rawLineCount = 0;

  function buildLineIndex(text) {
    var offsets = [0];
    var i = 0;
    while (true) {
      i = text.indexOf('\n', i);
      if (i === -1) break;
      offsets.push(i + 1);
      i++;
    }
    return offsets;
  }

  function rawLineText(i) {
    var start = rawLineOffsets[i];
    var end = (i + 1 < rawLineCount) ? rawLineOffsets[i + 1] - 1 : sourceText.length;
    if (end > start && sourceText.charCodeAt(end - 1) === 13) end--; // 去掉 \r（CRLF）
    return sourceText.slice(start, end);
  }

  function padLeft(n, width) {
    var s = String(n);
    while (s.length < width) s = ' ' + s;
    return s;
  }

  /**
   * 原文片段 → span，按「水平窗口」切分。
   *
   * 背景：压缩 / 转义后，整个文档是一行几 MB 的超长文本。如果整行塞进一个
   * 文本节点，浏览器的文本 shaping 是超线性成本直接假死；如果按 512 字符无脑
   * 切块，12MB 会切出 2 万多个 DOM 节点，反而更慢（那次就是切太碎翻车的）。
   * 正确做法是「窗口化」：只渲染 scrollLeft 附近一段（左右各留 RAW_WINDOW
   * 字符缓冲），两侧用省略号占位提示，滚动时重渲染窗口。DOM 节点数恒定，
   * 与行有多长无关。
   */
  var RAW_WINDOW = 4000;
  var rawScrollLeft = 0;

  function rawTextSpan(text) {
    var span = el('span', 'raw-tx');
    if (text.length <= RAW_WINDOW * 2) {
      span.textContent = text;               // 短行：整行一个节点
      return span;
    }
    var start = Math.max(0, rawScrollLeft - RAW_WINDOW);
    var end = Math.min(text.length, start + RAW_WINDOW * 2);
    if (start > 0) span.appendChild(el('span', 'raw-hint', '…'));
    span.appendChild(document.createTextNode(text.slice(start, end)));
    if (end < text.length) span.appendChild(el('span', 'raw-hint', '…'));
    return span;
  }

  /** 载入大文本：建行索引 + 渲染可视区。行索引用 indexOf 逐行推进，O(行数) 而非逐字符。 */
  function showRawView() {
    rawLineOffsets = buildLineIndex(sourceText);
    rawLineCount = rawLineOffsets.length;
    rawSizerEl.style.height = (rawLineCount * RAW_LINE_H) + 'px';
    rawViewEl.scrollTop = 0;
    renderRawVisible();
  }

  function hideRawView() {
    rawViewEl.hidden = true;
    rawContentEl.textContent = '';
    rawSizerEl.style.height = '1px';
    rawLineOffsets = [];
    rawLineCount = 0;
  }

  /** 只渲染可视区内的行（上下各多留 30/60 行缓冲，滚动时不露白） */
  function renderRawVisible() {
    var viewportH = rawViewEl.clientHeight || 400;
    var start = Math.max(0, Math.floor(rawViewEl.scrollTop / RAW_LINE_H) - 30);
    var visible = Math.ceil(viewportH / RAW_LINE_H);
    var end = Math.min(rawLineCount, start + visible + 60);

    rawScrollLeft = rawViewEl.scrollLeft;
    rawContentEl.style.transform = 'translateY(' + (start * RAW_LINE_H) + 'px)';
    var digits = String(rawLineCount).length;
    var frag = document.createDocumentFragment();
    for (var i = start; i < end; i++) {
      var line = el('div', 'raw-line');
      line.appendChild(el('span', 'raw-ln', padLeft(i + 1, digits)));
      line.appendChild(rawTextSpan(rawLineText(i)));
      frag.appendChild(line);
    }
    rawContentEl.textContent = '';
    rawContentEl.appendChild(frag);
  }

  /**
   * 统一入口：设置输入文本，并按体积决定走「可编辑 textarea」还是
   * 「虚拟滚动只读原文视图」。大文本绝不进原生 textarea。
   * @param {string} text 新文本
   */
  function setInputText(text) {
    sourceText = text;
    if (text.length > BIG_INPUT_THRESHOLD) {
      inputEl.hidden = true;
      rawViewEl.hidden = false;
      showRawView();
    } else {
      inputEl.hidden = false;
      hideRawView();
      inputEl.value = text;
    }
    updateStats();
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /* ---------------- 查看器 ---------------- */

  function viewerOptions() {
    return Object.assign({}, settings, {
      interactive: true,
      // 独立页没有「宿主网页」，不需要还原/关闭按钮
      onRestore: null,
      onClose: null,
      onThemeChange: function (resolved, raw) {
        // 让主题作用到整个页面（顶栏 / 输入面板 / 背景），而不是只有右侧查看器。
        // resolved 是「auto」折算后的实际主题（light|dark），raw 是用户选的档位。
        applyPageTheme(resolved);
        // 大文档视图是独立的 CM 实例，主题要单独推给它
        if (bigView) bigView.setOptions({ dark: resolved === 'dark' });
      },
      onSettingsChange: function (patch) {
        Object.assign(settings, patch);
        NS.saveSettings(patch);
      }
    });
  }

  function ensureViewer() {
    if (!viewer) viewer = NS.createViewer(viewerHost, viewerOptions());
    return viewer;
  }

  function showOutput(show) {
    if (!show) {
      viewerHost.hidden = true;
      bigHost.hidden = true;
      welcomeEl.hidden = false;
      return;
    }
    welcomeEl.hidden = true;
    // 具体显示哪个宿主由 doFormat / doFormatBig 决定，这里只保证「有东西可见」
    if (!bigHost.hidden) return;
    viewerHost.hidden = false;
  }

  /* ---------------- 大文档视图（CodeMirror 6 虚拟化） ---------------- */

  var bigHost = $('bigView');
  var bigView = null;
  /** null = 自动判断；true/false = 用户在设置里手动指定 */
  var bigMode = null;
  /** 超过这个体积默认走大文档视图。600KB 的 JSON 树视图已接近千行，滚动开始发涩 */
  var BIG_MIN_CHARS = 600 * 1024;
  /** 大文档视图可用时，自动格式化的体积上限放宽到 64MB（虚拟化渲染与行数无关） */
  var BIG_AUTO_MAX = 64 * 1024 * 1024;

  function resolvedTheme() {
    var t = settings.theme;
    if (t === 'auto') {
      t = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
        ? 'dark' : 'light';
    }
    return t;
  }

  /**
   * 是否该用大文档视图。
   *
   * 不再拿 hasRawRisk 当门槛：bigview.js 内部把排版分成两条路——没有「写不回去
   * 的写法」时用原生 JSON.parse + JSON.stringify（最快），命中 \uXXXX / \/ /
   * 16 位以上整数时改用字符扫描（只加换行缩进，原文字节级保留）。所以带大整数
   * 的大文档也能进虚拟化视图，不会再像以前那样退回几十秒才建完的树视图。
   */
  function useBigView(text) {
    if (!NS.hasBigView) return false;
    if (bigMode === false) return false;
    if (bigMode === true) return true;
    return text.length >= BIG_MIN_CHARS;
  }

  /**
   * 自动格式化的体积上限。大文档视图可用时放宽到 64MB：
   * 虚拟化渲染与文档行数无关，20MB 的大写按旧上限只会得到一句「内容过大」，
   * 那正是用户抱怨「大 JSON 点了半天看不到完整结果」的来源之一。
   */
  function autoSizeLimit() {
    if (NS.hasBigView && bigMode !== false) {
      return Math.max(settings.maxAutoSize, BIG_AUTO_MAX);
    }
    return settings.maxAutoSize;
  }

  function ensureBigView() {
    if (!bigView) {
      bigView = NS.createBigView(bigHost, {
        indent: numberOr(settings.indent, 2),
        wrap: !!settings.wrap,
        fontSize: numberOr(settings.fontSize, 14),
        lineNumbers: !!settings.lineNumbers,
        dark: resolvedTheme() === 'dark'
      });
    }
    return bigView;
  }

  function hideBigView() {
    bigHost.hidden = true;
    // 离开大文档视图：顶栏与底部状态带恢复正常，输入栏也交回给用户
    setBigDocMode(false);
  }

  function doFormatBig(text) {
    // 先让宿主可见、并切到「单栏 + 收窄」布局，再创建 CodeMirror ——
    // CM 会量可视区尺寸，在 display:none 或半宽状态下建实例会量错。
    viewerHost.hidden = true;
    welcomeEl.hidden = true;
    bigHost.hidden = false;
    setBigDocMode(true);

    var bv = ensureBigView();
    // 排版是同步的：29MB 压缩 JSON → 约 700ms（原生） / 1.2s（保真路径）。
    // 先让浏览器把「解析中…」画出来再开工，否则用户会看到界面卡住不动。
    var run = function () {
      var ok = bv.setText(text);
      var st = bv.getState();
      if (!ok) {
        setPill('is-err', '格式有误');
        setMessage(st.error || '内容不是合法 JSON', 'err');
      } else {
        setPill('is-ok', st.exact ? '格式化成功' : '格式化成功（原文保真）');
        // 底部状态带只留最要紧的三个数：行数 / 耗时 / 渲染方式。
        // 完整说明放进 title —— 长文案换行会把底部撑成两排，白占 JSON 的高度。
        setMessage('大文档模式 · ' + st.rows.toLocaleString('zh-CN') + ' 行 · ' +
                   st.elapsed + 'ms · 虚拟化渲染', 'ok');
        msgEl.title = '虚拟化渲染：只绘制视口附近的行，' + st.rows.toLocaleString('zh-CN') +
                      ' 行也能立刻出现、滚动流畅；支持折叠、搜索、行号与括号匹配';
      }
      updateStats();
    };

    setPill('is-busy', '解析中…');
    setMessage('大文档模式 · 正在排版 ' + formatBytes(text.length) + '…');
    // rAF 之后再做重活，保证「解析中…」这一帧真的被画出来
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run);
    else setTimeout(run, 0);
  }

  function numberOr(v, fallback) {
    var n = parseInt(v, 10);
    return isNaN(n) ? fallback : n;
  }

  /* ---------------- 入场动效 ---------------- */

  function playEnterAnimation() {
    var rows = viewerHost.querySelectorAll('.jf-row');
    var limit = Math.min(rows.length, STAGGER_ROWS);
    for (var i = 0; i < limit; i++) {
      rows[i].style.animationDelay = (i * STAGGER_STEP) + 'ms';
    }

    // 只加不清。
    // 之前是「remove → 逼一次重排 → add」，目的只是让动画能重新触发；但那一瞬间
    // 所有行会从 opacity:1 掉回基态再跳到 opacity:0，观感就是整块内容闪一下。
    // 实际上 format() 每次都会重建 .jf-row（render 重跑），新元素天然会从
    // 0% 关键帧开始播；所以只补一个「没开就开」的判断就够了。
    // 注意：折叠/展开不会走到这里，所以那些内部重渲染不会跟着播动画。
    viewerHost.classList.add('is-fresh');

    if (animTimer) clearTimeout(animTimer);
    var total = limit * STAGGER_STEP + ROW_DURATION + 120;
    animTimer = setTimeout(function () {
      animTimer = null;
      viewerHost.classList.remove('is-fresh');
    }, total);
  }

  /* ---------------- 格式化 ---------------- */

  function format(force, animate) {
    var text = sourceText;

    if (!text.trim()) {
      lastRendered = null;
      setBigDocMode(false);
      if (viewer) showOutput(false);
      setPill('', '就绪');
      setMessage('');
      return;
    }

    // 超大内容不自动渲染，避免刚载入就把页面卡住
    if (!force && text.length > autoSizeLimit()) {
      setPill('is-err', '内容过大');
      setMessage('超过自动格式化上限 ' + formatBytes(autoSizeLimit()) +
                 '，按 Ctrl+Enter 强制格式化');
      return;
    }

    // 先让宿主可见，再创建查看器，避免在 display:none 下量尺寸
    showOutput(true);

    /* 大文档走 CodeMirror 虚拟化视图：树视图是一节点一行 DOM，
       20MB JSON 是 61 万行，分帧建完要几十秒；虚拟化只画可见的几十行。 */
    if (useBigView(text)) {
      lastRendered = text;
      doFormatBig(text);
      return;
    }

    hideBigView();
    var v = ensureViewer();

    var changed = text !== lastRendered;
    lastRendered = text;

    doFormat(v, text, animate, changed);
  }

  function doFormat(v, text, animate, changed) {
    var ok = v.setText(text);
    if (ok) {
      var st = v.getState();
      setPill('is-ok', st.lenient ? '宽松解析成功' : '格式化成功');
      setMessage(st.lenient ? '已容忍注释 / 单引号 / 尾随逗号 / 裸键名' : '', st.lenient ? 'ok' : '');
      if (animate && changed) playEnterAnimation();
    } else {
      setPill('is-err', '格式有误');
      setMessage('右栏已标出出错的行号、列号与位置', 'err');
    }
  }

  function scheduleFormat(fast) {
    updateStats();
    // 超大内容：同步给出「内容过大」提示，不要等 220ms 防抖的 setTimeout——
    // 那会被浏览器后续的重排推迟，用户看到的反馈就延迟了数秒。
    if (sourceText.length > autoSizeLimit()) {
      setPill('is-err', '内容过大');
      setMessage('超过自动格式化上限 ' + formatBytes(autoSizeLimit()) +
                 '，按 Ctrl+Enter 强制格式化');
      if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
      return;
    }
    // 解析状态只体现在状态胶囊上。不要在这里给面板加 class，
    // 否则连续输入时 220ms 防抖会让面板反复亮灭（就是「窗口闪动」的来源之一）。
    setPill('is-busy', '解析中…');
    if (debounceTimer) clearTimeout(debounceTimer);
    // fast=true（粘贴 / 拖入大文本）：防抖是给「连续打字」用的，
    // 一次性灌进来的大文本不会再有后续输入，220ms 纯属白等。
    // 用 setTimeout(0) 而不是同步调 format：先让浏览器把原文视图画出来，
    // 用户立刻能看到内容进去，右侧树随后跟上。
    debounceTimer = setTimeout(function () {
      debounceTimer = null;
      format(false, inputKind !== 'typing');
      inputKind = 'typing';
    }, fast ? 0 : DEBOUNCE_MS);
  }

  function formatNow() {
    if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
    updateStats();
    format(true, inputKind !== 'typing');
    inputKind = 'typing';
  }

  /* ---------------- 输入事件 ---------------- */

  inputEl.addEventListener('input', function (e) {
    // 大输入模式下 textarea 已被隐藏，不会有 input 事件；正常路径下
    // 直接读 textarea 的值作为内存源（小文本，实时编辑）。
    sourceText = inputEl.value;
    if (e && e.inputType === 'insertFromPaste') inputKind = 'paste';
    scheduleFormat();
  });

  // 拦截粘贴：剪贴板文本超过阈值时不写回 textarea（避免浏览器渲染超长文本
  // 卡死主线程），而是直接存内存源并进入大输入模式。这是「粘贴大 JSON 不卡」
  // 的关键——文本从剪贴板读进来后，不再经过 textarea 这道昂贵的渲染。
  // 挂在 document 上而非 textarea：大输入模式下 textarea 被隐藏，焦点会落到
  // body，粘贴事件只会冒泡到 document；这里统一兜底，用户能直接再粘一份替换。
  document.addEventListener('paste', function (e) {
    var cd = e.clipboardData || window.clipboardData;
    var text = cd && cd.getData ? cd.getData('text/plain') : '';
    if (!text || text.length <= BIG_INPUT_THRESHOLD) return; // 小文本走 textarea 默认路径
    e.preventDefault();                 // 阻止浏览器把大文本塞进 textarea
    setInputText(text);
    inputKind = 'paste';
    scheduleFormat(true);               // 大文本粘贴不需要防抖，立即格式化
  });

  // 虚拟原文视图：滚动与尺寸变化时重渲染可视区
  rawViewEl.addEventListener('scroll', renderRawVisible, { passive: true });
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(function () {
      if (!rawViewEl.hidden) renderRawVisible();
    }).observe(rawViewEl);
  }

  inputEl.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      formatNow();
    }
  });

  /* ---------------- 拖入文件 ----------------
     输入栏在大文档模式下会收起（.is-solo），所以拖放不能只绑在它上面，
     否则「收起输入栏后拖文件进去」会没反应。两条面板都接。 */

  var dropZones = [panelInput, $('panelOutput')].filter(Boolean);

  dropZones.forEach(function (zone) {
    ['dragenter', 'dragover'].forEach(function (type) {
      zone.addEventListener(type, function (e) {
        e.preventDefault();
        zone.classList.add('is-dragover');
      });
    });

    ['dragleave', 'drop'].forEach(function (type) {
      zone.addEventListener(type, function (e) {
        e.preventDefault();
        if (type === 'dragleave' && zone.contains(e.relatedTarget)) return;
        zone.classList.remove('is-dragover');
      });
    });

    zone.addEventListener('drop', function (e) {
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        var text = String(reader.result || '');
        setInputText(text);
        fileInfoEl.textContent = file.name + ' · ' + formatBytes(file.size);
        inputKind = 'drop';
        setMessage('已读入 ' + file.name, 'ok');
        formatNow();
      };
      reader.onerror = function () {
        setPill('is-err', '读取失败');
        setMessage('无法读取文件：' + file.name, 'err');
      };
      reader.readAsText(file, 'utf-8');
    });
  });

  /* ---------------- 按钮 ---------------- */

  $('btnSample').addEventListener('click', function () {
    setInputText(SAMPLE);
    fileInfoEl.textContent = '';
    inputKind = 'drop';   // 视作一次整块替换，播放动效
    setMessage('已载入示例数据', 'ok');
    formatNow();
  });

  $('btnClear').addEventListener('click', function () {
    sourceText = '';
    inputEl.value = '';
    inputEl.hidden = false;
    hideRawView();
    fileInfoEl.textContent = '';
    lastRendered = null;
    updateStats();
    if (viewer) showOutput(false);
    setPill('', '就绪');
    setMessage('');
    inputEl.focus();
  });

  // 设置页只在扩展环境里存在；脱离扩展时干脆把按钮藏掉，免得点了没反应
  var btnOptions = $('btnOptions');
  if (HAS_EXT) {
    btnOptions.addEventListener('click', function () {
      if (chrome.runtime.openOptionsPage) chrome.runtime.openOptionsPage();
    });
  } else if (btnOptions) {
    btnOptions.hidden = true;
  }

  /* ---------------- 输入转换工具（转换 ▾ 菜单） ----------------
   * 五个功能全部是 O(n) 单遍处理，不做 JSON.parse / stringify 整棵树
   * （压缩尤其如此：直接对原文做空白/注释剥离，大整数精度原样保留，
   * 宽松写法——单引号、注释、尾随逗号——也不会出错）。
   * 结果统一走 setInputText：大文本自动切虚拟原文视图，不卡 textarea。
   */

  // 中文（所有非 ASCII 可见字符）→ \uXXXX。单遍正则替换，原生实现最快。
  function toUnicode(text) {
    return text.replace(/[\u0080-\uFFFF]/g, function (ch) {
      var code = ch.charCodeAt(0).toString(16);
      while (code.length < 4) code = '0' + code;
      return '\\u' + code;
    });
  }

  // \uXXXX → 原字符。代理对（emoji 等）由 fromCharCode 自然拼回。
  function fromUnicode(text) {
    return text.replace(/\\u([0-9a-fA-F]{4})/g, function (m, hex) {
      return String.fromCharCode(parseInt(hex, 16));
    });
  }

  // 转义：整段文本变成一个带引号的 JSON 字符串（native stringify，O(n)）
  function escapeJson(text) {
    return JSON.stringify(text);
  }

  // 去除转义：剥掉一层 JSON 字符串包装。失败返回 null（调用方提示）。
  function unescapeJson(text) {
    var t = text.replace(/^\uFEFF/, '').trim();
    if (!t) return null;
    // 标准形态：整体就是一个带引号的 JSON 字符串
    try {
      var v = JSON.parse(t);
      if (typeof v === 'string') return v;
    } catch (e) { /* 落到下面的兜底 */ }
    // 兜底：用户手动删过外层引号，内容还是 \" 转义形态 → 补一对引号再解
    if (/^[\[{]/.test(t)) return null; // 看着就是未转义的 JSON，没有可去的转义
    try {
      var v2 = JSON.parse('"' + t + '"');
      if (typeof v2 === 'string') return v2;
    } catch (e2) { /* 忽略 */ }
    return null;
  }

  /** Uint16Array 前 len 个码元 → 字符串。分块 fromCharCode，避免超长参数列表爆栈 */
  function charCodesToString(buf, len) {
    var CHUNK = 8192;
    var out = [];
    for (var i = 0; i < len; i += CHUNK) {
      var end = Math.min(i + CHUNK, len);
      out.push(String.fromCharCode.apply(null, buf.subarray(i, end)));
    }
    return out.join('');
  }

  // 压缩：单遍扫描，字符串原样保留（不解析内容），剥掉字符串外的空白与注释。
  // 相比 JSON.parse+stringify 的优势：大整数精度不丢、宽松写法不报错、更快。
  //
  // 性能要点：输出一定不长于输入（只删字符），所以一次性分配 Uint16Array 当写指针，
  // 比旧实现「push 上百万个分片再 join」快得多——11MB 美化过的 JSON 里空白成片出现，
  // 旧写法会攒出上百万个 JS 小字符串，光分配和 join 就要一两秒。
  function minifyJsonText(src) {
    var n = src.length;
    var buf = new Uint16Array(n);
    var w = 0;
    var i = 0;
    while (i < n) {
      var c = src.charCodeAt(i);
      if (c === 34 /* " */ || c === 39 /* ' */) {
        // 字符串整体搬运（宽松写法支持单引号），内部空白不动
        var j = i + 1;
        while (j < n) {
          var cj = src.charCodeAt(j);
          if (cj === 92 /* \ */) { j += 2; continue; }
          j++;
          if (cj === c) break;
        }
        if (j > n) j = n;
        while (i < j) buf[w++] = src.charCodeAt(i++);
        continue;
      }
      if (c === 47 /* / */) {
        var nx = src.charCodeAt(i + 1);
        if (nx === 47) {                  // 行注释 → 一个空格占位
          var k = src.indexOf('\n', i);
          i = k < 0 ? n : k;
          buf[w++] = 32;
          continue;
        }
        if (nx === 42) {                  // 块注释 → 一个空格占位
          var k2 = src.indexOf('*/', i + 2);
          i = k2 < 0 ? n : k2 + 2;
          buf[w++] = 32;
          continue;
        }
      }
      if (c === 32 || c === 9 || c === 10 || c === 13) { i++; continue; } // 空白
      buf[w++] = c;
      i++;
    }
    return charCodesToString(buf, w);
  }

  var XFORMS = {
    toUnicode:   { fn: toUnicode,   label: '中文转 Unicode' },
    fromUnicode: { fn: fromUnicode, label: 'Unicode 转中文' },
    escape:      { fn: escapeJson,  label: '转义' },
    unescape:    { fn: unescapeJson, label: '去除转义' },
    minify:      { fn: minifyJsonText, label: '压缩' }
  };

  function applyXform(kind) {
    var spec = XFORMS[kind];
    if (!spec) return;
    var text = sourceText;
    if (!text) { setMessage('输入为空，没有可转换的内容', 'err'); return; }
    var t0 = performance.now ? performance.now() : Date.now();
    var out;
    try {
      out = spec.fn(text);
    } catch (err) {
      setMessage(spec.label + '失败：' + err.message, 'err');
      return;
    }
    if (out == null) {
      setMessage(spec.label + '：内容不是转义后的 JSON 字符串，无转义可去', 'err');
      return;
    }
    if (out === text) {
      setMessage(spec.label + '：转换后内容未变化', 'ok');
      return;
    }
    setInputText(out);
    inputKind = 'drop'; // 视作整块替换，右侧播放动效
    var ms = Math.round((performance.now ? performance.now() : Date.now()) - t0);
    formatNow();
    setMessage(spec.label + '完成 · ' + formatBytes(out.length) + ' · ' + ms + 'ms', 'ok');
  }

  /* 两枚双向按钮：方向自动识别 */
  var btnUniToggle = $('btnUniToggle');
  if (btnUniToggle) btnUniToggle.addEventListener('click', function () {
    // 检测到 \u 转义 → 还原成中文；否则 → 转成 \uXXXX
    applyXform(/\\u[0-9a-fA-F]{4}/.test(sourceText) ? 'fromUnicode' : 'toUnicode');
  });
  var btnEscToggle = $('btnEscToggle');
  if (btnEscToggle) btnEscToggle.addEventListener('click', function () {
    // 整段以引号开头 → 还原；否则 → 转义
    var t = (sourceText || '').replace(/^\uFEFF/, '').trim();
    applyXform(t.charAt(0) === '"' ? 'unescape' : 'escape');
  });
  var btnMinify = $('btnMinify');
  if (btnMinify) btnMinify.addEventListener('click', function () {
    applyXform('minify');
  });

  /* ---------------- 可拖动分隔条 ---------------- */

  var SPLIT_KEY = 'jfEditorSplitPercent';
  var SPLIT_MIN = 20;
  var SPLIT_MAX = 68;
  var SPLIT_DEFAULT = 36;
  var splitPct = SPLIT_DEFAULT;

  try {
    var saved = parseFloat(localStorage.getItem(SPLIT_KEY));
    if (saved >= SPLIT_MIN && saved <= SPLIT_MAX) splitPct = saved;
  } catch (e) { /* localStorage 不可用时用默认值 */ }

  function applySplit() {
    document.documentElement.style.setProperty('--split', splitPct + '%');
  }

  function setSplit(pct) {
    splitPct = Math.max(SPLIT_MIN, Math.min(SPLIT_MAX, pct));
    applySplit();
  }

  function rememberSplit() {
    try { localStorage.setItem(SPLIT_KEY, String(splitPct)); } catch (e) { /* ignore */ }
  }

  applySplit();

  var dragging = false;

  splitterEl.addEventListener('pointerdown', function (e) {
    if (e.button !== 0) return;
    e.preventDefault();
    dragging = true;
    splitterEl.classList.add('is-dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    if (splitterEl.setPointerCapture) splitterEl.setPointerCapture(e.pointerId);
  });

  splitterEl.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    var rect = $('workspace').getBoundingClientRect();
    if (!rect.width) return;
    setSplit(((e.clientX - rect.left) / rect.width) * 100);
  });

  function endDrag(e) {
    if (!dragging) return;
    dragging = false;
    splitterEl.classList.remove('is-dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    if (e && e.pointerId !== undefined && splitterEl.releasePointerCapture) {
      try { splitterEl.releasePointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    }
    rememberSplit();
  }

  splitterEl.addEventListener('pointerup', endDrag);
  splitterEl.addEventListener('pointercancel', endDrag);

  splitterEl.addEventListener('dblclick', function () {
    setSplit(SPLIT_DEFAULT);
    rememberSplit();
  });

  splitterEl.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') { setSplit(splitPct - 2); e.preventDefault(); }
    else if (e.key === 'ArrowRight') { setSplit(splitPct + 2); e.preventDefault(); }
    else if (e.key === 'Home') { setSplit(SPLIT_DEFAULT); e.preventDefault(); }
    else return;
    rememberSplit();
  });

  /* ---------------- 全屏 / 沉浸阅读 ---------------- */

  var workspaceEl = $('workspace');
  var btnFullscreen = $('btnFullscreen');
  var fsLabel = $('fsLabel');
  var rootEl = document.documentElement;

  function focusActive() {
    return rootEl.classList.contains('is-fullscreen');
  }

  /** 只切布局与文案，不碰浏览器全屏 API —— 这样即使全屏被拒也有一致的观感 */
  function applyFocus(on) {
    var active = !!on;
    rootEl.classList.toggle('is-fullscreen', active);
    workspaceEl.classList.toggle('is-focus', active);
    if (fsLabel) fsLabel.textContent = active ? '退出全屏' : '全屏';
    if (btnFullscreen) {
      btnFullscreen.setAttribute('aria-pressed', active ? 'true' : 'false');
      btnFullscreen.title = active ? '退出全屏（Esc）' : '全屏查看（F）';
    }
  }

  function enterFocus() {
    applyFocus(true);
    if (document.fullscreenElement || !rootEl.requestFullscreen) return;
    var p = rootEl.requestFullscreen();
    // 被策略拒（例如嵌在 iframe 里没给 allowfullscreen）时静默失败，
    // 上一步的沉浸布局照常生效
    if (p && p.catch) p.catch(function () { /* ignore */ });
  }

  function exitFocus() {
    applyFocus(false);
    if (document.fullscreenElement && document.exitFullscreen) {
      var p = document.exitFullscreen();
      if (p && p.catch) p.catch(function () { /* ignore */ });
    }
  }

  function toggleFocus() {
    if (focusActive()) exitFocus();
    else enterFocus();
  }

  if (btnFullscreen) btnFullscreen.addEventListener('click', toggleFocus);

  // 用户按 Esc / F11 退出浏览器全屏时，把沉浸布局一并收掉，避免两边状态不一致
  document.addEventListener('fullscreenchange', function () {
    if (!document.fullscreenElement && focusActive()) applyFocus(false);
  });

  document.addEventListener('keydown', function (e) {
    // 不在真实全屏里时，Esc 也应收起沉浸布局
    if (e.key === 'Escape' && focusActive() && !document.fullscreenElement) {
      exitFocus();
      e.preventDefault();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    // 正在输入框里打字时不抢 F 键，否则 JSON 里的 f 会触发全屏
    var t = e.target;
    if (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.isContentEditable)) return;
    if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      toggleFocus();
    }
  });

  /* ---------------- 输入栏收起 / 大文档最大化 ---------------- */

  /* 两件互相独立但常一起生效的事：
       is-solo    —— 左栏与分隔条让位，输出独占整宽（JSON 区从半宽变整宽）；
       is-bigdoc  —— 大文档正在展示，顶栏、外边距、底部状态带一起收窄。
     自动判定（大文档 → 收起）与手动开关共存：用户点过一次按钮就固定为手动，
     不再被内容切换来回夺走控制权。 */
  var btnSolo = $('btnSolo');
  var soloLabel = $('soloLabel');
  /** null = 跟随内容自动；true / false = 用户手动指定 */
  var soloMode = null;
  /** 自动判定结果：大文档展示时为 true */
  var autoSolo = false;

  function soloWanted() {
    return soloMode === null ? autoSolo : soloMode;
  }

  function applySoloState() {
    var on = soloWanted();
    workspaceEl.classList.toggle('is-solo', on);
    if (btnSolo) {
      btnSolo.setAttribute('aria-pressed', on ? 'true' : 'false');
      btnSolo.title = on ? '展开左侧输入栏' : '收起左侧输入栏，把宽度让给 JSON';
    }
    if (soloLabel) soloLabel.textContent = on ? '显示输入' : '输入栏';
  }

  if (btnSolo) {
    btnSolo.addEventListener('click', function () {
      soloMode = !soloWanted();
      applySoloState();
    });
  }

  /** 大文档模式开关：收窄顶栏与底部状态带，并自动收起输入栏 */
  function setBigDocMode(on) {
    autoSolo = !!on;
    document.body.classList.toggle('is-bigdoc', !!on);
    applySoloState();
  }

  /* ---------------- 设置同步 ---------------- */

  /**
   * 把主题作用到整个编辑页（不只是查看器面板）。
   * 在 <html> 上挂 data-theme，配合 editor.css 的 html[data-theme="dark"] 覆盖
   * 全部 token（--page/--panel/--text/--border 等），实现「全局深色」。
   */
  function applyPageTheme(resolved) {
    if (resolved === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
  }

  function applySettingsToViewer() {
    if (viewer) viewer.updateOptions(viewerOptions());
    if (bigView) {
      bigView.setOptions({
        indent: numberOr(settings.indent, 2),
        wrap: !!settings.wrap,
        fontSize: numberOr(settings.fontSize, 14),
        lineNumbers: !!settings.lineNumbers,
        dark: resolvedTheme() === 'dark'
      });
    }
  }

  NS.loadSettings().then(function (loaded) {
    settings = loaded;
    applySettingsToViewer();
    // viewer 尚未创建时（打开页面还没粘贴内容），也要按已存主题铺底色
    if (!viewer) {
      var theme = settings.theme;
      if (theme === 'auto') {
        theme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark' : 'light';
      }
      applyPageTheme(theme);
    }
  });

  if (HAS_EXT && chrome.storage && chrome.storage.onChanged) {
    chrome.storage.onChanged.addListener(function (changes, area) {
      if (area !== 'sync' && area !== 'local') return;
      var patch = {};
      Object.keys(changes).forEach(function (k) {
        if (k in NS.DEFAULTS) patch[k] = changes[k].newValue;
      });
      if (!Object.keys(patch).length) return;
      Object.assign(settings, patch);
      applySettingsToViewer();
    });
  }

  /* ---------------- 启动 ---------------- */

  /* macOS 深色主题下默认字体平滑会把浅色字渲染得偏重发糊，挂个 html.is-mac
     让 CSS 降级成灰阶抗锯齿；Windows/Linux 不加（ClearType 更清晰）。 */
  if (/Mac/i.test((navigator.platform || '') + ' ' + (navigator.userAgent || ''))) {
    document.documentElement.classList.add('is-mac');
  }

  updateStats();
  showOutput(false);
  // 初始化「输入栏收起」按钮的文案/状态（默认展开）
  applySoloState();
  // 打开就聚焦，点完扩展图标可以直接 Ctrl+V
  inputEl.focus();
})();
