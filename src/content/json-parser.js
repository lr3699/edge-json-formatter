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
  function parse(text, options) {
    options = options || {};
    if (typeof text !== 'string') text = String(text);
    var expanded = options.defaultExpanded !== false; // 默认展开（与查看器既有行为一致）
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

  /** 统计节点数与最大深度 */
  function stats(root) {
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
    joinKey: joinKey,
    JsonParseError: JsonParseError
  };
})();
