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

    rawContentEl.style.transform = 'translateY(' + (start * RAW_LINE_H) + 'px)';
    var digits = String(rawLineCount).length;
    var frag = document.createDocumentFragment();
    for (var i = start; i < end; i++) {
      var line = el('div', 'raw-line');
      line.appendChild(el('span', 'raw-ln', padLeft(i + 1, digits)));
      line.appendChild(el('span', 'raw-tx', rawLineText(i)));
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
    viewerHost.hidden = !show;
    welcomeEl.hidden = show;
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
      if (viewer) showOutput(false);
      setPill('', '就绪');
      setMessage('');
      return;
    }

    // 超大内容不自动渲染，避免刚载入就把页面卡住
    if (!force && text.length > settings.maxAutoSize) {
      setPill('is-err', '内容过大');
      setMessage('超过自动格式化上限 ' + formatBytes(settings.maxAutoSize) +
                 '，按 Ctrl+Enter 强制格式化');
      return;
    }

    // 先让宿主可见，再创建查看器，避免在 display:none 下量尺寸
    showOutput(true);
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

  function scheduleFormat() {
    updateStats();
    // 超大内容：同步给出「内容过大」提示，不要等 220ms 防抖的 setTimeout——
    // 那会被浏览器后续的重排推迟，用户看到的反馈就延迟了数秒。
    if (sourceText.length > settings.maxAutoSize) {
      setPill('is-err', '内容过大');
      setMessage('超过自动格式化上限 ' + formatBytes(settings.maxAutoSize) +
                 '，按 Ctrl+Enter 强制格式化');
      if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
      return;
    }
    // 解析状态只体现在状态胶囊上。不要在这里给面板加 class，
    // 否则连续输入时 220ms 防抖会让面板反复亮灭（就是「窗口闪动」的来源之一）。
    setPill('is-busy', '解析中…');
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      debounceTimer = null;
      format(false, inputKind !== 'typing');
      inputKind = 'typing';
    }, DEBOUNCE_MS);
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
    scheduleFormat();
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

  /* ---------------- 拖入文件 ---------------- */

  ['dragenter', 'dragover'].forEach(function (type) {
    panelInput.addEventListener(type, function (e) {
      e.preventDefault();
      panelInput.classList.add('is-dragover');
    });
  });

  ['dragleave', 'drop'].forEach(function (type) {
    panelInput.addEventListener(type, function (e) {
      e.preventDefault();
      if (type === 'dragleave' && panelInput.contains(e.relatedTarget)) return;
      panelInput.classList.remove('is-dragover');
    });
  });

  panelInput.addEventListener('drop', function (e) {
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

  // 压缩：单遍扫描，字符串原样保留（不解析内容），剥掉字符串外的空白与注释。
  // 相比 JSON.parse+stringify 的优势：大整数精度不丢、宽松写法不报错、更快。
  function minifyJsonText(src) {
    var n = src.length;
    var parts = [];
    var i = 0;
    var start = 0; // 当前未消费块的起点
    while (i < n) {
      var ch = src.charCodeAt(i);
      if (ch === 34 /* " */ || ch === 39 /* ' */) {
        // 字符串整体拷贝（宽松写法支持单引号），内部空白不动
        var j = i + 1;
        while (j < n) {
          var c = src.charCodeAt(j);
          if (c === 92 /* \ */) { j += 2; continue; }
          if (c === ch) { j++; break; }
          j++;
        }
        if (start < i) parts.push(src.slice(start, i));
        parts.push(src.slice(i, j));
        i = start = j;
        continue;
      }
      if (ch === 47 /* / */) {
        var nx = src.charCodeAt(i + 1);
        if (nx === 47) { // 行注释 → 一个空格占位
          var k = src.indexOf('\n', i);
          if (k < 0) k = n;
          if (start < i) parts.push(src.slice(start, i));
          parts.push(' ');
          i = start = k;
          continue;
        }
        if (nx === 42) { // 块注释 → 一个空格占位
          var k2 = src.indexOf('*/', i + 2);
          k2 = k2 < 0 ? n : k2 + 2;
          if (start < i) parts.push(src.slice(start, i));
          parts.push(' ');
          i = start = k2;
          continue;
        }
      }
      if (ch === 32 || ch === 9 || ch === 10 || ch === 13) { // 空白
        if (start < i) parts.push(src.slice(start, i));
        i++;
        start = i;
        continue;
      }
      i++;
    }
    if (start < n) parts.push(src.slice(start, n));
    return parts.join('');
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

  updateStats();
  showOutput(false);
  // 打开就聚焦，点完扩展图标可以直接 Ctrl+V
  inputEl.focus();

  /* ---- 网页版钩子（由 tools/build-site.js 注入，src/ 里没有） ---- */
  NS.getEditorSettings = function () {
    return Object.assign({}, settings);
  };

  /** 设置面板改一项 → 立即生效 + 落盘 + 同步整页主题 */
  NS.applyEditorSettings = function (patch) {
    Object.assign(settings, patch);
    NS.saveSettings(patch);
    applySettingsToViewer();
    var t = settings.theme;
    if (t === "auto") {
      t = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark" : "light";
    }
    applyPageTheme(t);
  };

  /** 从外部灌入一段文本并立即格式化（URL 加载 / 分享链接用） */
  NS.setEditorText = function (text) {
    setInputText(text);
    inputKind = "drop";
    formatNow();
  };

  /** 读取当前输入源文本（大文本模式下 textarea 被隐藏，必须走这里） */
  NS.getEditorText = function () {
    return sourceText;
  };

})();
