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

  function parseStrict(text) {
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
        expanded: false,
        keyNode: null,
        parent: null,
        path: '',
        indexInParent: 0
      };
    }

    function readString(depth) {
      var start = i;
      i++; // 开引号
      var out = '';
      while (true) {
        if (i >= n) fail('字符串缺少结束引号', start);
        var c = text[i];
        if (c === '"') {
          i++;
          break;
        }
        if (c === '\\') {
          var e = text[i + 1];
          switch (e) {
            case '"': out += '"'; i += 2; break;
            case '\\': out += '\\'; i += 2; break;
            case '/': out += '/'; i += 2; break;
            case 'b': out += '\b'; i += 2; break;
            case 'f': out += '\f'; i += 2; break;
            case 'n': out += '\n'; i += 2; break;
            case 'r': out += '\r'; i += 2; break;
            case 't': out += '\t'; i += 2; break;
            case 'u': {
              var hex = text.substr(i + 2, 4);
              if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail('无效的 \\u 转义序列', i);
              out += String.fromCharCode(parseInt(hex, 16));
              i += 6;
              break;
            }
            default:
              if (e === undefined) fail('字符串在转义符后意外结束', i);
              fail('无效的转义字符 “\\' + e + '”', i);
          }
          continue;
        }
        if (c === '\n' || c === '\r') fail('字符串中不能出现未转义的换行', i);
        out += c;
        i++;
      }
      return prim('string', out, start, i, depth);
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
   */
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
        var m = /^[A-Za-z_$][A-Za-z0-9_$]*/.exec(text.slice(i));
        if (m) {
          var after = text.slice(i + m[0].length).replace(/^\s+/, '');
          if (after[0] === ':') {
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
   * @returns {{root: object, lenient: boolean}}
   */
  function parse(text, options) {
    options = options || {};
    if (typeof text !== 'string') text = String(text);
    try {
      return { root: parseStrict(text), lenient: false };
    } catch (err) {
      if (!options.lenient) throw err;
      var relaxedText = relax(text);
      try {
        return { root: parseStrict(relaxedText), lenient: true };
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
