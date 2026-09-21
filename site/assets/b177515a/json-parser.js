/**
 * 带「原始切片」的 JSON 解析器。
 *
 * 与 JSON.parse 的区别：
 *  - 每个节点保留源码中的精确文本（raw），因此
 *      600653836507516928 这类超过 Number.MAX_SAFE_INTEGER 的大整数不会被精度截断；
 *      "\u4e2d\u6587" 这类转义也不会被静默还原。
 *  - 每个节点记录 start / end 偏移，可精确定位语法错误所在的行列。
 *  - 支持宽松模式（注释、单引号、尾随逗号、无引号键）。
 */
(function () {
  'use strict';

  var NS = (globalThis.__EDGE_JSON_FORMATTER__ =
    globalThis.__EDGE_JSON_FORMATTER__ || {});

  var uid = 0;

  function JsonParseError(message, index, text) {
    var pre = text.slice(0, index);
    var lineStart = pre.lastIndexOf('\n') + 1;
    var lineEnd = text.indexOf('\n', lineStart);
    if (lineEnd === -1) lineEnd = text.length;

    this.name = 'JsonParseError';
    this.message = message;
    this.index = index;
    this.line = pre.split('\n').length;
    this.column = index - lineStart + 1;
    this.lineText = text.slice(lineStart, lineEnd);
    this.caret = new Array(Math.max(1, this.column)).join(' ') + '^';
    Error.call(this, message);
  }
  JsonParseError.prototype = Object.create(Error.prototype);
  JsonParseError.prototype.constructor = JsonParseError;

  function isDigit(c) {
    return c >= '0' && c <= '9';
  }

  function parseStrict(text, meta, defaultExpanded) {
    var i = text.charCodeAt(0) === 0xfeff ? 1 : 0;
    var n = text.length;

    function fail(msg, at) {
      throw new JsonParseError(msg, at === undefined ? i : at, text);
    }

    function ws() {
      while (i < n) {
        var c = text.charCodeAt(i);
        if (c === 0x20 || c === 0x09 || c === 0x0a || c === 0x0d) i++;
        else return;
      }
    }

    function prim(type, value, start, end, depth) {
      /* 节点数与最大深度在解析途中顺手累加，容器 expanded 一次定好。
         以前是解析完再 stats() + setAllExpanded() 两趟全树遍历，对 11MB
         文档是百万级函数调用，白跑。这里把三件事合并进 O(1) 的节点构造。 */
      meta.count++;
      if (depth > meta.depth) meta.depth = depth;
      var isContainer = (type === 'object' || type === 'array');
      return {
        id: uid++,
        type: type,
        value: value,
        raw: text.slice(start, end),
        start: start,
        end: end,
        depth: depth,
        entries: null,
        items: null,
        expanded: isContainer && defaultExpanded === true,
        keyNode: null,
        parent: null,
        path: '',
        indexInParent: 0
      };
    }

    function readString(depth) {
      var start = i;
      i++; // 开引号
      // 性能要点一：必须先 indexOf 定位结束引号，再在「引号界定的一段」里找反斜杠。
      // 旧版先在全文上 indexOf('\\', i) 找转义——文档里只要没有任何反斜杠，
      // 这个查找每次都要扫到文档末尾，几十万个短字符串就是 O(n²)，大 JSON 直接卡死。
      // 性能要点二：结果必须用数组分片 + 最后一次性 join。旧版 out += 每遇一个
      // 转义就把已累积的整个字符串重新拷贝一遍——一段含十几万个 \uXXXX 的
      // 大字符串就是 O(n²)（约几十 GB 的内存搬运），主线程直接卡死几十秒。
      var parts = [];
      while (true) {
        var q = text.indexOf('"', i);
        if (q === -1) fail('字符串缺少结束引号', start);
        var run = text.slice(i, q); // 本次结束引号之前的整段
        var s = run.indexOf('\\');
        if (s === -1) {
          // 无转义：整段一次入队，字符串结束
          var nl = run.search(/[\n\r]/);
          if (nl !== -1) fail('字符串中不能出现未转义的换行', i + nl);
          parts.push(run);
          i = q + 1;
          break;
        }
        // 段内含转义：先入队无转义前段，再按转义符逐个处理
        if (s > 0) {
          var nl2 = run.slice(0, s).search(/[\n\r]/);
          if (nl2 !== -1) fail('字符串中不能出现未转义的换行', i + nl2);
          parts.push(run.slice(0, s));
        }
        var bs = i + s; // 反斜杠绝对位置
        var e = text[bs + 1];
        switch (e) {
          case '"': case '\\': case '/':
            parts.push(e); i = bs + 2; break;
          case 'b': parts.push('\b'); i = bs + 2; break;
          case 'f': parts.push('\f'); i = bs + 2; break;
          case 'n': parts.push('\n'); i = bs + 2; break;
          case 'r': parts.push('\r'); i = bs + 2; break;
          case 't': parts.push('\t'); i = bs + 2; break;
          case 'u': {
            var hex = text.substr(bs + 2, 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail('无效的 \\u 转义序列', bs);
            parts.push(String.fromCharCode(parseInt(hex, 16)));
            i = bs + 6;
            break;
          }
          default:
            if (e === undefined) fail('字符串在转义符后意外结束', bs);
            fail('无效的转义字符 “\\' + e + '”', bs);
        }
      }
      return prim('string', parts.join(''), start, i, depth);
    }

    function readNumber(depth) {
      var start = i;
      if (text[i] === '-') i++;
      if (text[i] === '0') {
        i++;
      } else {
        if (!isDigit(text[i])) fail('数字格式不正确', start);
        while (i < n && isDigit(text[i])) i++;
      }
      if (text[i] === '.') {
        i++;
        if (!isDigit(text[i])) fail('小数点后缺少数字');
        while (i < n && isDigit(text[i])) i++;
      }
      if (text[i] === 'e' || text[i] === 'E') {
        i++;
        if (text[i] === '+' || text[i] === '-') i++;
        if (!isDigit(text[i])) fail('指数部分缺少数字');
        while (i < n && isDigit(text[i])) i++;
      }
      var raw = text.slice(start, i);
      return prim('number', Number(raw), start, i, depth);
    }

    function readObject(depth) {
      var start = i;
      i++; // {
      var node = prim('object', undefined, start, start, depth);
      node.entries = [];
      ws();
      if (text[i] === '}') {
        i++;
        node.end = i;
        node.raw = text.slice(start, i);
        return node;
      }
      while (true) {
        ws();
        if (text[i] !== '"') fail('对象的键必须是双引号字符串');
        var keyNode = readString(depth + 1);
        ws();
        if (text[i] !== ':') fail('键之后缺少冒号 “:”');
        i++;
        ws();
        var valueNode = readValue(depth + 1);
        node.entries.push({ keyNode: keyNode, value: valueNode });
        ws();
        if (text[i] === ',') {
          i++;
          ws();
          if (text[i] === '}') { i++; break; } // 容忍尾随逗号
          continue;
        }
        if (text[i] === '}') { i++; break; }
        if (i >= n) fail('对象缺少右花括号 “}”', start);
        fail('对象中缺少逗号或右花括号 “}”，遇到 “' + text[i] + '”');
      }
      node.end = i;
      node.raw = text.slice(start, i);
      return node;
    }

    function readArray(depth) {
      var start = i;
      i++; // [
      var node = prim('array', undefined, start, start, depth);
      node.items = [];
      ws();
      if (text[i] === ']') {
        i++;
        node.end = i;
        node.raw = text.slice(start, i);
        return node;
      }
      while (true) {
        ws();
        node.items.push(readValue(depth + 1));
        ws();
        if (text[i] === ',') {
          i++;
          ws();
          if (text[i] === ']') { i++; break; } // 容忍尾随逗号
          continue;
        }
        if (text[i] === ']') { i++; break; }
        if (i >= n) fail('数组缺少右方括号 “]”', start);
        fail('数组中缺少逗号或右方括号 “]”，遇到 “' + text[i] + '”');
      }
      node.end = i;
      node.raw = text.slice(start, i);
      return node;
    }

    function readValue(depth) {
      ws();
      if (i >= n) fail('意外的内容结束：JSON 不完整');
      var c = text[i];
      if (c === '{') return readObject(depth);
      if (c === '[') return readArray(depth);
      if (c === '"') return readString(depth);
      if (c === '-' || isDigit(c)) return readNumber(depth);
      if (text.substr(i, 4) === 'true') { var t = i; i += 4; return prim('boolean', true, t, i, depth); }
      if (text.substr(i, 5) === 'false') { var f = i; i += 5; return prim('boolean', false, f, i, depth); }
      if (text.substr(i, 4) === 'null') { var nl = i; i += 4; return prim('null', null, nl, i, depth); }
      fail('无法识别的字符 “' + c + '”');
    }

    ws();
    if (i >= n) fail('内容为空，不是有效的 JSON');
    var root = readValue(0);
    ws();
    if (i < n) {
      fail('JSON 结束后存在多余内容（第 ' + (i + 1) + ' 个字符起）');
    }
    return root;
  }

  /**
   * 宽松化预处理：去注释、单引号转双引号、去尾随逗号、给裸键补引号。
   * 使用带括号栈的状态机，避免误伤字符串内部。
   *
   * 性能：裸键匹配必须用 sticky 正则（BARE_KEY）直接在原文上 exec。
   * 早期写法对每个裸键都先 text.slice(i) 再配全局搜索正则——等于把
   * 「当前位置到结尾」的整段字符串复制一遍，大 JSON 下是 O(n²)，直接卡死。
   * 注意：本注释里不能出现正则字面量，否则其结束斜杠会提前终止这个块注释。
   */
  var BARE_KEY = /[A-Za-z_$][A-Za-z0-9_$]*/y;
  var WS_RE = /\s/;

  function relax(text) {
    var out = [];
    var i = 0;
    var n = text.length;
    var stack = [];
    var pendingKey = false; // 当前是否处于「对象键位置」
    var inStr = false;
    var inLineComment = false;
    var inBlockComment = false;

    function push(ch) {
      out.push(ch);
    }

    while (i < n) {
      var c = text[i];
      var c2 = text[i + 1];

      if (inLineComment) {
        if (c === '\n') { inLineComment = false; push(c); }
        i++;
        continue;
      }
      if (inBlockComment) {
        if (c === '*' && c2 === '/') { inBlockComment = false; i += 2; continue; }
        i++;
        continue;
      }
      if (inStr) {
        push(c);
        if (c === '\\') { if (c2 !== undefined) push(c2); i += 2; continue; }
        if (c === '"') { inStr = false; }
        i++;
        continue;
      }

      if (c === '/' && c2 === '/') { inLineComment = true; i += 2; continue; }
      if (c === '/' && c2 === '*') { inBlockComment = true; i += 2; continue; }

      if (c === '"') {
        inStr = true;
        push(c);
        i++;
        pendingKey = false;
        continue;
      }

      if (c === "'") {
        // 单引号字符串 → 双引号字符串
        var j = i + 1;
        var buf = '';
        while (j < n) {
          if (text[j] === '\\') { buf += text[j] + (text[j + 1] || ''); j += 2; continue; }
          if (text[j] === "'") break;
          buf += text[j];
          j++;
        }
        push('"' + buf.replace(/"/g, '\\"') + '"');
        i = j + 1;
        pendingKey = false;
        continue;
      }

      if (c === '{' || c === '[') {
        stack.push(c);
        push(c);
        i++;
        pendingKey = c === '{';
        continue;
      }
      if (c === '}' || c === ']') {
        stack.pop();
        // 去掉 } / ] 前面的尾随逗号
        for (var k = out.length - 1; k >= 0; k--) {
          if (/\s/.test(out[k])) continue;
          if (out[k] === ',') out.splice(k, 1);
          break;
        }
        push(c);
        i++;
        pendingKey = false;
        continue;
      }
      if (c === ',') {
        push(c);
        i++;
        pendingKey = stack[stack.length - 1] === '{';
        continue;
      }
      if (c === ':') {
        push(c);
        i++;
        pendingKey = false;
        continue;
      }

      if (pendingKey && /[A-Za-z_$]/.test(c)) {
        // sticky 正则直接在原文上匹配；旧写法 exec(text.slice(i)) 每个裸键
        // 都复制「当前位置到结尾」的整段字符串，大 JSON 下是 O(n²)。
        BARE_KEY.lastIndex = i;
        var m = BARE_KEY.exec(text);
        if (m) {
          var k = i + m[0].length;
          while (k < n && WS_RE.test(text[k])) k++;
          if (text[k] === ':') {
            push('"' + m[0] + '"');
            i += m[0].length;
            continue;
          }
        }
      }

      push(c);
      i++;
    }

    return out.join('');
  }

  /**
   * 解析 JSON 文本。
   * @param {string} text
   * @param {{lenient?: boolean}} [options]
   * @returns {{root: object, lenient: boolean, count: number, depth: number}}
   *          count / depth 由解析过程顺手统计，调用方不必再遍历一次树。
   */
  /**
   * 快路径（一）：原生 JSON.parse。
   *
   * 实测 22MB / 32 万节点：手写解析器 415ms，原生 JSON.parse 43ms（差近 10 倍）。
   *
   * 快路径（二）：惰性树。这是数量级提升的关键。
   * 原生解析只能给出一棵普通 JS 对象树，把它逐节点包成带 raw/偏移的节点
   * 实测要 286ms（32 万个节点），会把原生解析省下来的时间全部吃回去。
   * 但查看器一次只渲染几千行（TOTAL_ROWS = 6000），所以整棵树根本不该建。
   * 于是：原生对象直接包一层惰性节点，容器的 entries / items 是「按需物化」
   * 的数组视图——被渲染到的下标才生成节点。渲染 6000 行就只物化几千个节点。
   *
   * 代价是拿不到每个值的原文偏移，因此做了这些取舍：
   *   - raw 改用原型 getter 按需还原（零逐节点成本）：
   *       字符串 / 键 = JSON.stringify(value)
   *       数字       = String(value)
   *       容器       = ''（查看器不读容器的 raw）
   *     所以必须先过 hasRawRisk() 守卫，否则显示会变样。
   *   - start / end 置 -1：只有报错行列会用到，而快路径不会失败。
   *
   * 触发条件（任一不满足就退回手写解析器）：
   *   - 文本 >= FAST_PATH_MIN（小文件手写解析器足够快，不动它可零回归）
   *   - 非 lenient 请求（宽松模式必须走手写预处理）
   *   - hasRawRisk() 未命中：没有 \\uXXXX / \\/ 这类无法还原的转义，
   *     且字符串外没有 16 位以上连续数字
   *   - JSON.parse 成功（失败则退回，手写解析器才能给出行列与宽松重试）
   *   - 键序未被引擎重排：不含以数字开头的键（会被排到最前）
   */
  var FAST_PATH_MIN = 256 * 1024;

  /* ---------------- 惰性树 ---------------- */

  /** 以数字开头的键会被引擎重排（数字键排最前），与原文顺序不符 */
  var NUM_KEY = /^\d/;
  var IDX_RE = /^\d+$/;
  var ARRAY_PROTO = Array.prototype;
  var HAS_OWN = Object.prototype.hasOwnProperty;

  /* 会话（uid 计数器 / 默认展开态 / 已物化容器清单）不用模块级变量存：
     它跟着每个节点的 __sess 走。否则连续两次 parse 后再去物化前一棵树
     （比如旧 DOM 的折叠闭包还活着），uid/展开态/容器清单会串进新会话。 */

  /** 惰性节点共享原型：raw / entries / items 都在这里按需生成 */
  var LAZY_PROTO = null;
  function lazyProto() {
    if (LAZY_PROTO) return LAZY_PROTO;
    var p = Object.create(Object.prototype);
    function def(name, get) {
      Object.defineProperty(p, name, {
        configurable: true, enumerable: false, get: get
      });
    }
    // 原文还原：字符串与键用 JSON.stringify（与「保留转义」的显示语义一致），
    // 数字用 String(value)。二者的前提都由 hasRawRisk() 保证。
    def('raw', function () {
      var r = this.__raw;
      if (r === undefined) {
        var t = this.type;
        r = t === 'string' ? JSON.stringify(this.value)
          : t === 'number' || t === 'boolean' ? String(this.value)
            : t === 'null' ? 'null' : '';
        this.__raw = r;
      }
      return r;
    });
    def('entries', function () {
      if (this.type !== 'object') return null;
      return this.__kid || (this.__kid = lazyKids(this));
    });
    def('items', function () {
      if (this.type !== 'array') return null;
      return this.__kid || (this.__kid = lazyKids(this));
    });
    LAZY_PROTO = p;
    return p;
  }

  /** 原生值 → 惰性节点。只包一层，不递归：这就是「不建整棵树」的落点 */
  function lazyNode(v, depth, keyNode, parent, indexInParent, s) {
    var type = v === null ? 'null'
      : Array.isArray(v) ? 'array'
        : typeof v === 'object' ? 'object'
          : typeof v;                       // string / number / boolean
    var isC = type === 'object' || type === 'array';
    var o = Object.create(lazyProto());
    o.id = s.uid++;
    o.type = type;
    o.value = isC ? undefined : v;
    o.depth = depth;
    o.start = -1;
    o.end = -1;
    o.expanded = isC && s.deflt;
    o.keyNode = keyNode || null;
    o.parent = parent || null;
    o.path = '';
    o.indexInParent = indexInParent || 0;
    o.__n = isC ? v : undefined;
    o.__kid = null;
    o.__sess = s;                           // 会话随节点走，物化子节点时取用
    if (isC) s.nodes.push(o);               // 供 setAllExpanded 用，避免全树行走
    return o;
  }

  /**
   * 容器子节点的惰性数组视图。
   *
   * 用 Proxy 套在真数组上，是为了让调用方（查看器 / 测试）继续按
   * `list.length` / `list[i]` / `list.slice()` 用，不用改任何调用点：
   *  - length、下标取值是 O(1) 且只在被取到时才物化那一个子节点；
   *  - slice / filter / map 这类批量方法按需整体物化（只有「按键排序」
   *    与紧凑/美化导出才会走到，都是用户主动动作）。
   * 渲染 6000 行的场景下，一个 30 万元素的数组只会生成几千个节点。
   */
  function lazyKids(node) {
    var native = node.__n;
    var s = node.__sess;
    var isArr = node.type === 'array';
    var keys = isArr ? null : Object.keys(native);
    var len = isArr ? native.length : keys.length;
    var kids = new Array(len);              // 只占长度，内容全部留空
    var keyNodes = isArr ? null : new Array(len);

    function at(i) {
      var c = kids[i];
      if (c !== undefined) return c;
      // 语义必须与手写解析器一致：对象的 entries[i] 是 {keyNode, value} 键值对，
      // 数组的 items[i] 就是子节点本身。
      if (isArr) {
        c = lazyNode(native[i], node.depth + 1, null, node, i, s);
      } else {
        var kn = keyNodes[i] ||
          (keyNodes[i] = lazyNode(keys[i], node.depth + 1, null, node, i, s));
        c = {
          keyNode: kn,
          value: lazyNode(native[keys[i]], node.depth + 1, kn, node, i, s)
        };
      }
      kids[i] = c;
      return c;
    }

    function all() {
      for (var i = 0; i < len; i++) if (kids[i] === undefined) at(i);
      return kids;
    }

    return new Proxy(kids, {
      get: function (t, p) {
        if (p === 'length') return len;
        if (typeof p === 'string') {
          if (IDX_RE.test(p)) {
            var i = +p;
            return i < len ? at(i) : undefined;
          }
          if (HAS_OWN.call(ARRAY_PROTO, p)) {
            var f = ARRAY_PROTO[p];
            if (typeof f === 'function') {
              return function () { return f.apply(all(), arguments); };
            }
          }
          return undefined;
        }
        if (p === Symbol.iterator) {
          return function () { return all()[Symbol.iterator](); };
        }
        return undefined;
      }
    });
  }

  /**
   * 原生结构的统计遍历：数节点、量深度，顺带校验键序。
   * 全程不建节点对象，32 万节点约 20ms；用显式栈避免深嵌套爆栈。
   */
  function measureNative(v, meta, checkKeys) {
    var stack = [v];
    var depths = [0];
    while (stack.length) {
      var cur = stack.pop();
      var d = depths.pop();
      meta.count++;
      if (d > meta.depth) meta.depth = d;
      if (Array.isArray(cur)) {
        for (var i = cur.length - 1; i >= 0; i--) {
          stack.push(cur[i]);
          depths.push(d + 1);
        }
      } else if (cur && typeof cur === 'object') {
        var ks = Object.keys(cur);
        // 键也算节点：手写解析器把键当字符串节点解析并计数，
        // 这里必须对齐，否则状态栏的「N 个节点」两条路径对不上
        meta.count += ks.length;
        for (var j = ks.length - 1; j >= 0; j--) {
          if (checkKeys && NUM_KEY.test(ks[j])) throw FAST_FALLBACK;
          stack.push(cur[ks[j]]);
          depths.push(d + 1);
        }
      }
    }
  }

  /**
   * 原文保真守卫：命中任一条就整体退回手写解析器（它逐字符解析，原文精确）。
   *
   *  1) 字符串里出现 \\uXXXX 或 \\/ 这类「写法不唯一」的转义。原文无法从
   *     还原后的字符反推：源码写 "\u4e2d"，还原成「中」之后
   *     JSON.stringify 只会给出 "中"，原文就丢了。keepEscape 默认开启、
   *     正是要显示源码原文，所以只能退回。
   *     注意：\\" \\\\ \\n \\t \\r \\b \\f 这些转义写法是唯一的，
   *     JSON.stringify 能一字不差地还原出来，不构成风险，不必退回——
   *     这一条把「文档里出现过任何反斜杠」的粗判据收窄了很多，
   *     带引号、带换行的大文档照样能走快路径。
   *  2) 字符串外出现 16 位以上连续数字。超过 2^53 后 String(value) 已经丢精度，
   *     而快路径的 raw 正是 String(value) 还原的，显示会变成被截断的近似值。
   *     这是本工具明确承诺保留的大整数，必须退回。
   *
   * 不设防的差异（可接受）：数字的书写形式被规范化——
   * 1e3 → 1000、1.50 → 1.5、-0 → 0。数值完全一致，只是写法变了。
   */
  var RISKY_NUM = /[0-9]{16}/;
  function hasRawRisk(text) {
    var n = text.length;
    /* nb 是「下一个反斜杠」的游标，只前进不后退，所以整体扫描仍是 O(n)。
       早先的写法对每个字符串都 text.indexOf('\\', s)：反斜杠一旦全部分布在
       文档前段（本项目的 22MB 样本里只有 112 个 \n），后面几十万个字符串
       每次都要扫到文档结尾，直接退化成 O(n²)——实测 30 秒。 */
    var nb = text.indexOf('\\');
    var i = 0;
    while (i < n) {
      var q = text.indexOf('"', i);
      if (q === -1) q = n;
      if (q - i > 15 && RISKY_NUM.test(text.slice(i, q))) return true;
      if (q >= n) break;
      // 跳过字符串：遇到转义就先看转义字符本身（写法不唯一的转义无法还原）
      var s = q + 1;
      var e;
      for (;;) {
        while (nb !== -1 && nb < s) nb = text.indexOf('\\', nb + 1);
        var dq = text.indexOf('"', s);
        if (nb !== -1 && (dq === -1 || nb < dq)) {
          var ec = text.charAt(nb + 1);
          if (ec === 'u' || ec === '/') return true;
          s = nb + 2;                 // 跳过这个转义序列，继续找结束引号
          continue;
        }
        if (dq === -1) { e = n; break; }
        e = dq;
        break;
      }
      i = e + 1;
    }
    return false;
  }

  /** 快路径专属的中止信号：构建阶段发现不兼容就整体退回手写解析器 */
  var FAST_FALLBACK = {};

  /** 开一次惰性会话并包出根节点。O(1)：不递归、不预建任何子节点 */
  function buildFromNative(native, expanded) {
    var sess = { uid: 0, deflt: expanded === true, nodes: [] };
    return lazyNode(native, 0, null, null, 0, sess);
  }

  /**
   * 展开 / 折叠全部。
   * 惰性树下不能走 walk()——那会把整棵树物化出来（32 万节点、数百毫秒）。
   * 改为：翻转会话默认态（决定后续新物化节点的初始态），
   * 再只把「已经物化出来的容器」改掉（渲染上限 6000 行，数量可控）。
   */
  function setAllExpanded(root, expanded) {
    if (!root) return;
    var on = expanded === true;
    var sess = root.__sess;
    if (sess) {
      sess.deflt = on;
      for (var i = 0; i < sess.nodes.length; i++) sess.nodes[i].expanded = on;
      return;
    }
    walk(root, function (n) {
      if (n.type === 'object' || n.type === 'array') n.expanded = on;
    });
  }

  function parse(text, options) {
    options = options || {};
    if (typeof text !== 'string') text = String(text);
    var expanded = options.defaultExpanded !== false; // 默认展开（与查看器既有行为一致）

    // 快路径：只在「大文本 + 严格模式 + 原文保真」时启用。
    // noFastPath 供测试/排障用：强制走手写解析器做对照。
    if (!options.lenient && !options.noFastPath &&
        text.length >= FAST_PATH_MIN && !hasRawRisk(text)) {
      var src = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;  // 去 BOM
      try {
        var native = JSON.parse(src);          // ① 引擎解析：比手写快近 10 倍
        var meta0 = { count: 0, depth: 0 };
        measureNative(native, meta0, true);    // ② 数节点/深度，顺带校验键序
        // ③ 只包一层惰性根：整棵树的节点等被渲染到再物化
        return {
          root: buildFromNative(native, expanded),
          lenient: false,
          count: meta0.count,
          depth: meta0.depth
        };
      } catch (err) {
        if (err !== FAST_FALLBACK && !(err instanceof SyntaxError)) throw err;
        // 落回手写解析器：JSON.parse 失败时它能给出行列与宽松重试
      }
    }

    var meta = { count: 0, depth: 0 };
    try {
      return {
        root: parseStrict(text, meta, expanded),
        lenient: false,
        count: meta.count,
        depth: meta.depth
      };
    } catch (err) {
      if (!options.lenient) throw err;
      var relaxedText = relax(text);
      var meta2 = { count: 0, depth: 0 };
      try {
        return {
          root: parseStrict(relaxedText, meta2, expanded),
          lenient: true,
          count: meta2.count,
          depth: meta2.depth
        };
      } catch (err2) {
        throw err; // 报原始错误，信息更有意义
      }
    }
  }

  /** 遍历树（先序） */
  function walk(node, visit, path, indexInParent, parent, keyNode) {
    if (!node) return;
    node.path = path === undefined ? '$' : path;
    node.indexInParent = indexInParent || 0;
    node.parent = parent || null;
    node.keyNode = keyNode || null;
    if (visit) visit(node);
    if (node.type === 'object') {
      for (var i = 0; i < node.entries.length; i++) {
        var entry = node.entries[i];
        walk(entry.value, visit, joinKey(node.path, entry.keyNode.value), i, node, entry.keyNode);
      }
    } else if (node.type === 'array') {
      for (var j = 0; j < node.items.length; j++) {
        walk(node.items[j], visit, node.path + '[' + j + ']', j, node, null);
      }
    }
  }

  var SIMPLE_KEY = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

  function joinKey(basePath, key) {
    if (SIMPLE_KEY.test(key)) return basePath + '.' + key;
    return basePath + '["' + String(key).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"]';
  }

  /** 统计节点数与最大深度。惰性树直接数原生结构，不走节点树 */
  function stats(root) {
    if (root && root.__sess) {
      var m = { count: 0, depth: 0 };
      measureNative(root.__n, m, false);
      return m;
    }
    var count = 0;
    var maxDepth = 0;
    walk(root, function (node) {
      count++;
      if (node.depth > maxDepth) maxDepth = node.depth;
    });
    return { count: count, depth: maxDepth };
  }

  NS.parser = {
    parse: parse,
    relax: relax,
    walk: walk,
    stats: stats,
    setAllExpanded: setAllExpanded,
    joinKey: joinKey,
    JsonParseError: JsonParseError
  };
})();
