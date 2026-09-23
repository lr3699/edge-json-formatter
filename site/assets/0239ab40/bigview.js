/**
 * bigview.js —— 大文档视图：用 CodeMirror 6 渲染「格式化后的完整文本」。
 *
 * 为什么要它：树视图是「一个节点一个 DOM 行」，20MB JSON 是 61 万行 DOM，
 * 分帧建完要几十秒，主线程还一直忙。CodeMirror 6 是**虚拟化**的——
 * 不管文档多少行，只渲染视口附近那几十行，60 万行也是立刻出现、滚动流畅。
 * 顺带白拿折叠、搜索、行号、括号匹配、语法高亮。
 *
 * 分工（由 editor.js 决定）：
 *   - 小文档 → 现有树视图（可点键复制路径、逐节点折叠，交互更细）；
 *   - 大文档 → 本模块（完整、快、可搜索可折叠）。
 *
 * 依赖 src/vendor/codemirror.bundle.js（本地打包，MV3 无远程代码）。
 */
(function () {
  'use strict';

  var NS = globalThis.__EDGE_JSON_FORMATTER__;
  if (!NS) return;

  var CM = globalThis.JFCodeMirror;
  /** 环境里没加载 bundle 时（例如内容脚本接管页面），对外暴露能力位让调用方回退 */
  NS.hasBigView = !!CM;

  var DEF = { indent: 2, wrap: false, dark: false, fontSize: 14, lineNumbers: false };

  /* ==================== 排版两条路 ====================
   *
   * 实测（29MB 压缩单行，Node 22，见 tools/bench-bigformat.js）：
   *   A) JSON.parse + JSON.stringify(v,null,2)      ≈ 1.0s，输出 45.4MB
   *   B) 纯字符扫描（不建对象树、不重新序列化）      ≈ 1.1s，输出 45.4MB
   * 两者速度相当，差别在**保真**：
   *   A 会把 "\u4e2d" 展开成「中」、把 12345678901234567890 截成近似值；
   *   B 只加换行与缩进，其余字符原样搬运，escape 与大整数一字不差。
   *
   * 所以：能用 A 就用 A（省掉对象树的构建与回收），只要出现
   * hasRawRisk 命中的写法就整体改用 B —— 这正是本工具承诺的
   * 「大整数按原文保留」触发的场景，不能为了快把承诺丢掉。
   */

  function stripBom(text) {
    return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  }

  function indentUnitOf(indent) {
    if (indent === 'tab' || indent === 'Tab' || indent === '\t') return '\t';
    var n = parseInt(indent, 10);
    if (!n || n < 0) n = 2;
    return new Array(n + 1).join(' ');
  }

  function isWs(c) {
    return c === 32 || c === 9 || c === 10 || c === 13;
  }

  function nextMeaningful(text, i, n) {
    while (i < n && isWs(text.charCodeAt(i))) i++;
    return i;
  }

  /**
   * 保真排版器：单遍扫描，只做「丢空白 + 补换行缩进」，字符串与数字原样搬。
   * 顺带做括号配对与字符串收尾的结构体检（结构坏了会被调用方标成格式有误），
   * 但不做完整语法校验——那件事交给 JSON.parse。
   *
   * 复杂度 O(n)，只分配输出字符串，峰值内存与文档同量级（不建对象树）。
   */
  function scanPretty(text, unit, compact) {
    var n = text.length;
    var parts = [];
    var cache = [];
    var depth = 0;
    var i = 0;
    var last = 0;
    var problem = null;
    var stack = [];

    function indOf(d) {
      if (compact) return '';
      if (cache[d] === undefined) cache[d] = '\n' + unit.repeat(d);
      return cache[d];
    }

    while (i < n) {
      var c = text.charCodeAt(i);

      // 字符串：整段搬运（含转义），顺带检查收尾与裸换行
      if (c === 34) {
        i++;
        for (;;) {
          if (i >= n) {
            if (!problem) problem = '字符串没有收尾引号';
            break;
          }
          var d = text.charCodeAt(i);
          if (d === 92) { i += 2; continue; }   // 反斜杠：连同下一字符一起跳过
          if (d === 34) { i++; break; }
          if (d === 10 || d === 13) {
            if (!problem) problem = '字符串里出现了裸换行';
          }
          i++;
        }
        continue;
      }

      // 分隔空白：全部丢弃（原文换行/缩进会被重排，不能留在片段里）
      if (isWs(c)) {
        parts.push(text.slice(last, i));
        i++;
        last = i;
        continue;
      }

      if (c === 123 || c === 91) {            // {  [
        var close = c === 123 ? 125 : 93;
        var nx = nextMeaningful(text, i + 1, n);
        if (text.charCodeAt(nx) === close) {
          // 空容器：规范成 {} / []（原文的 "{ }" 里那点空白一并吃掉）
          parts.push(text.slice(last, i + 1), text[nx]);
          i = nx + 1;
          last = i;
          continue;
        }
        depth++;
        stack.push(c);
        parts.push(text.slice(last, i + 1), indOf(depth));  // 片段含 '{'
        i++;
        last = i;
        continue;
      }

      if (c === 125 || c === 93) {            // }  ]
        var want = c === 125 ? 123 : 91;
        if (stack.pop() !== want && !problem) problem = '括号不匹配';
        if (depth > 0) depth--;
        parts.push(text.slice(last, i), indOf(depth));      // 闭合符留给下一片段
        i++;
        last = i - 1;
        continue;
      }

      if (c === 44) {                         // ,
        parts.push(text.slice(last, i + 1), indOf(depth));  // 片段含 ','
        i++;
        last = i;
        continue;
      }

      if (c === 58) {                         // :
        parts.push(text.slice(last, i + 1), compact ? '' : ' ');  // 片段含 ':'
        i++;
        last = i;
        continue;
      }

      i++;                                    // 普通字符：留给片段
    }

    parts.push(text.slice(last));
    if (stack.length && !problem) problem = '括号没有闭合';
    return { text: parts.join(''), problem: problem };
  }

  /**
   * 生成排版后的完整文本。
   * 返回 { ok, text, problem, exact }
   *   ok      —— 是合法 JSON（false 时调用方标「格式有误」）
   *   exact   —— true 表示走了保真路径，escape / 大整数一字未改
   */
  function prettify(text, indent, compact) {
    var src = stripBom(String(text == null ? '' : text));
    var unit = indentUnitOf(indent);
    var risk = NS.parser && NS.parser.hasRawRisk ? NS.parser.hasRawRisk(src) : true;

    // 路径 A：没有任何「写不回去」的写法，交给引擎，最快
    if (!risk) {
      try {
        var v = JSON.parse(src);
        return {
          ok: true,
          exact: true,
          problem: null,
          text: compact ? JSON.stringify(v) : JSON.stringify(v, null, unit)
        };
      } catch (e) {
        // 非法 JSON（或原生解析放弃），落到扫描器给一份尽力排版
      }
    }

    // 路径 B：保真扫描
    var scanned = scanPretty(src, unit, compact);
    var ok = true;
    try {
      JSON.parse(src);
    } catch (e) {
      ok = false;
    }
    return { ok: ok, exact: false, problem: scanned.problem, text: scanned.text };
  }

  function buildTheme(dark) {
    return CM.EditorView.theme(
      {
        '&': {
          height: '100%',
          fontSize: 'var(--jf-big-font,14px)',
          backgroundColor: 'var(--jf-bg)',
          color: 'var(--jf-text)',
        },
        '.cm-scroller': {
          /* 字体继承 .jf-big 上的等宽栈，避免这里再写死一份字体名 */
          fontFamily: 'inherit',
          lineHeight: '1.55',
          overflow: 'auto',
        },
        '.cm-content': { padding: '6px 0' },
        '.cm-line': { padding: '0 10px' },
        '.cm-gutters': {
          backgroundColor: 'var(--jf-bg-alt)',
          color: 'var(--jf-muted)',
          border: 'none',
          borderRight: '1px solid var(--jf-border)',
        },
        '.cm-activeLineGutter': { backgroundColor: 'transparent' },
        '.cm-activeLine': { backgroundColor: 'transparent' },
        '.cm-foldGutter span': { cursor: 'pointer' },
        '.cm-selectionBackground, ::selection': { backgroundColor: 'var(--jf-sel,rgba(100,150,255,.25))' },
        '.cm-searchMatch': { backgroundColor: 'var(--jf-find,rgba(255,210,0,.35))' },
        '.cm-searchMatch.cm-searchMatch-selected': { backgroundColor: 'var(--jf-find-sel,rgba(255,150,0,.5))' },
        '.cm-panels': {
          backgroundColor: 'var(--jf-bg-alt)',
          color: 'var(--jf-fg)',
          borderColor: 'var(--jf-border)',
        },
        '.cm-panels input, .cm-panels button': {
          font: 'inherit',
          color: 'var(--jf-fg)',
          background: 'var(--jf-bg)',
          border: '1px solid var(--jf-border)',
          borderRadius: '4px',
          padding: '2px 6px',
        },
      },
      { dark: !!dark }
    );
  }

  function buildHighlight() {
    var t = CM.tags;
    return CM.syntaxHighlighting(
      CM.HighlightStyle.define([
        { tag: t.propertyName, color: 'var(--jf-key)' },
        { tag: t.string, color: 'var(--jf-str)' },
        { tag: t.number, color: 'var(--jf-num)' },
        { tag: t.bool, color: 'var(--jf-bool)' },
        { tag: t.null, color: 'var(--jf-null)' },
        { tag: t.separator, color: 'var(--jf-punct)' },
        { tag: t.brace, color: 'var(--jf-punct)' },
        { tag: t.squareBracket, color: 'var(--jf-punct)' },
        { tag: t.paren, color: 'var(--jf-punct)' },
        { tag: t.invalid, color: 'var(--jf-err,#e5484d)' },
      ])
    );
  }

  /**
   * 在 host 里挂一个只读的虚拟化 JSON 视图。
   * 返回 { setText, setOptions, getState, getText, format, foldAll, unfoldAll,
   *        openSearch, destroy }
   */
  NS.createBigView = function (host, opts) {
    if (!CM) throw new Error('CodeMirror bundle 未加载');
    var o = Object.assign({}, DEF, opts || {});
    var view = null;
    var themeComp = new CM.Compartment();
    var wrapComp = new CM.Compartment();
    /** 行号槽由「显示行号」设置控制，用 Compartment 动态挂载/摘除 */
    var gutterComp = new CM.Compartment();
    var state = {
      text: '', rows: 0, chars: 0, indent: o.indent, compact: false,
      error: null, exact: true, elapsed: 0,
    };

    // 借用树视图那套 token（--jf-bg / --jf-key / …）。
    // 树视图是运行时才注入样式表的，大文档视图可能先于它出现，所以自己兜一道。
    if (NS.installViewerStyles) NS.installViewerStyles(host);
    host.classList.add('jf-big');
    applyHostTheme();

    function applyHostTheme() {
      if (o.dark) host.setAttribute('data-theme', 'dark');
      else host.removeAttribute('data-theme');
      host.style.setProperty('--jf-big-font', (o.fontSize || DEF.fontSize) + 'px');
    }

    function extensions() {
      return [
        /* minimalSetup 而不是 basicSetup：后者无条件带行号槽，而「显示行号」
           在本扩展里是用户设置项（默认关闭），得由 gutterComp 按需挂载。 */
        CM.minimalSetup,
        gutterComp.of(o.lineNumbers ? CM.lineNumbers() : []),
        CM.foldGutter(),                     // 折叠槽（含 codeFolding）
        CM.keymap.of(CM.foldKeymap),         // 折叠快捷键
        CM.json(),
        CM.search({ top: true }),
        CM.EditorView.editable.of(false),
        CM.EditorState.readOnly.of(true),
        themeComp.of(buildTheme(o.dark)),
        buildHighlight(),
        wrapComp.of(o.wrap ? CM.EditorView.lineWrapping : []),
      ];
    }

    /** 排版 + 挂载。返回 true 表示文本是合法 JSON */
    function apply(text) {
      var t0 = (globalThis.performance || Date).now();
      var r = prettify(text, state.indent, state.compact);
      var out = r.text;

      if (view) { view.destroy(); view = null; }
      view = new CM.EditorView({
        state: CM.EditorState.create({ doc: out, extensions: extensions() }),
        parent: host,
      });
      /* 测试钩子：让验收脚本能摸到 CM 实例（foldState / syntaxTree 等内部状态） */
      host.__jfView = view;

      state.rows = view.state.doc.lines;
      state.chars = out.length;
      state.elapsed = Math.round((globalThis.performance || Date).now() - t0);
      state.exact = r.exact;
      state.error = r.ok ? null : (r.problem || '内容不是合法 JSON，已按结构尽量排版');
      return r.ok;
    }

    function setText(text) {
      state.text = String(text == null ? '' : text);
      return apply(state.text);
    }

    function format(indent, compact) {
      if (indent != null) state.indent = indent;
      if (compact != null) state.compact = !!compact;
      if (!state.text) return false;
      return apply(state.text);
    }

    function setOptions(patch) {
      if (!patch) return;
      var themeChanged = patch.dark != null && patch.dark !== o.dark;
      var fontChanged = patch.fontSize != null && patch.fontSize !== o.fontSize;
      var gutterChanged = patch.lineNumbers != null && patch.lineNumbers !== o.lineNumbers;
      var wrapChanged = patch.wrap != null && patch.wrap !== o.wrap;
      var indentChanged = patch.indent != null && patch.indent !== state.indent;
      Object.assign(o, patch);
      if (themeChanged || fontChanged) applyHostTheme();
      if (!view) return;
      if (gutterChanged) {
        view.dispatch({ effects: gutterComp.reconfigure(o.lineNumbers ? CM.lineNumbers() : []) });
      }
      if (themeChanged) view.dispatch({ effects: themeComp.reconfigure(buildTheme(o.dark)) });
      if (wrapChanged) {
        view.dispatch({
          effects: wrapComp.reconfigure(o.wrap ? CM.EditorView.lineWrapping : []),
        });
      }
      if (indentChanged) format(patch.indent, null);
    }

    function getState() {
      return {
        rows: state.rows,
        chars: state.chars,
        count: state.rows,
        depth: 0,
        error: state.error,
        bigView: true,
        exact: state.exact,
        elapsed: state.elapsed,
        line: view ? view.state.doc.lines : 0,
        // 工具条要拿当前是「美化」还是「压缩」来定按钮文案，别让调用方自己猜
        compact: !!state.compact,
      };
    }

    function getText() {
      return view ? view.state.doc.toString() : '';
    }

    /**
     * 扫描全文，数出「最外层」可折叠块（开括号行 → 闭括号行）。
     * 不用 CM.foldable：syntaxTree 是惰性解析的，大文档只解析视口附近，
     * 未解析区域 foldable 返回 null —— 这正是「折叠全部只折了顶部一段」的根因。
     * 单遍字符扫描自带字符串/转义状态机，与语法树无关，O(n)。
     */
    function collectOuterFolds(text) {
      var pairs = [];
      var stack = [];
      var line = 0;
      var inStr = false;
      var esc = false;
      for (var i = 0; i < text.length; i++) {
        var c = text.charCodeAt(i);
        if (inStr) {
          if (esc) esc = false;
          else if (c === 92) esc = true;          /* 反斜杠：下一个字符是转义 */
          else if (c === 34 || c === 10) inStr = false;  /* 引号闭合；裸换行视作坏字符串兜底 */
          continue;
        }
        if (c === 34) { inStr = true; continue; }  /* " */
        if (c === 123 || c === 91) stack.push(line);         /* { [ */
        else if (c === 125 || c === 93) {                    /* } ] */
          var open = stack.pop();
          if (open != null && line > open) pairs.push(open, line);
        } else if (c === 10) line++;
      }
      if (!pairs.length) return [];
      /* JSON 块严格嵌套：按开行排序后贪心只留最外层。
         内层折叠点会被外层折叠整体藏起来，压重叠的 foldEffect 没有意义。 */
      var idx = [];
      for (var k = 0; k < pairs.length; k += 2) idx.push([pairs[k], pairs[k + 1]]);
      idx.sort(function (a, b) { return a[0] - b[0] || b[1] - a[1]; });
      var out = [];
      var lastTo = -1;
      for (var k2 = 0; k2 < idx.length; k2++) {
        if (idx[k2][0] > lastTo) { out.push(idx[k2]); lastTo = idx[k2][1]; }
      }
      return out;
    }

    /**
     * 折叠全部：对每个最外层块压 foldEffect（从开括号行尾到闭括号行首）。
     * 返回压上的折叠数；一个都折不了时返回 0。
     */
    function foldAllView() {
      if (!view) return 0;
      var st = view.state;
      var doc = st.doc;
      var blocks = collectOuterFolds(doc.toString());
      var effects = [];
      for (var i = 0; i < blocks.length; i++) {
        var from = doc.line(blocks[i][0] + 1).to;   /* 开括号所在行的行尾 */
        var to = doc.line(blocks[i][1] + 1).from;   /* 闭括号所在行的行首 */
        if (to > from) effects.push(CM.foldEffect.of({ from: from, to: to }));
      }
      if (!effects.length) return 0;
      view.dispatch({ effects: effects });
      view.focus();
      return effects.length;
    }

    /**
     * 展开全部：从 foldState 字段里读出所有已折叠区间，逐个 unfoldEffect。
     * 注意 unfoldEffect 和 foldEffect 一样吃 {from,to} 区间，不是单个位置。
     */
    function unfoldAllView() {
      if (!view) return false;
      var st = view.state;
      var field = null;
      try {
        field = st.field(CM.foldState, false);
      } catch (e) {
        field = null;
      }
      if (!field) return false;
      var effects = [];
      field.between(0, st.doc.length, function (from, to) {
        effects.push(CM.unfoldEffect.of({ from: from, to: to }));
      });
      if (!effects.length) return false;
      view.dispatch({ effects: effects });
      view.focus();
      return true;
    }

    return {
      setText: setText,
      format: format,
      setOptions: setOptions,
      getState: getState,
      getText: getText,
      foldAll: foldAllView,
      unfoldAll: unfoldAllView,
      openSearch: function () { if (view) CM.openSearchPanel(view); },
      focus: function () { if (view) view.focus(); },
      destroy: function () {
        if (view) { view.destroy(); view = null; }
        try { delete host.__jfView; } catch (e) { host.__jfView = null; }
      },
      /** 大视图没有「复制值」这类节点级交互，调用方据此隐藏对应按钮 */
      isBig: true,
    };
  };

  /** 供测试直接调用排版器 */
  NS.bigViewPrettify = prettify;
})();
