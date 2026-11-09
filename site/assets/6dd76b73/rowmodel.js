/**
 * 行模型（visible-row pipeline）——大 JSON 树视图虚拟化的数据层。
 *
 * ## 为什么需要它
 *
 * 树视图原来是「一个节点一行真实 DOM」。22MB / 360,166 行的文档要 36 万行 DOM，
 * 浏览器必然崩——这正是以前必须有 TOTAL_ROWS = 6000 上限、以及「超过 600KB
 * 就切虚拟化视图」的原因。
 *
 * 业界可行解（Dadroit / JSON Hero / svelte-jsoneditor 一致）是换掉心智模型：
 * 不再想「嵌套 DOM 树」，而是维护一份**摊平后的可见行表**，渲染层只把视口内的
 * 几十行挂成 DOM。本模块就是那份行表。
 *
 * ## 行表里有什么
 *
 * 只存两个等长数组：
 *   rows[i]  —— 这一行对应的节点引用
 *   kinds[i] —— 这一行的两个比特：bit0 = 开行/闭行，bit1 = 是不是最后一个兄弟
 *
 * 一个非空容器占两行：开行（`"key": {`，折叠时带 `… N 个字段` 摘要）+ 闭行
 * （`}`），和美化输出的排版一一对应。空容器（`{}` / `[]`）和叶子节点各占一行。
 * 折叠的容器只贡献它那两行——后代完全不进表，也不会被物化。
 *
 * 「是不是最后一个兄弟」放进 kinds 而不是让渲染层去问 `indexInParent`：
 *  - 「按键排序」打开后显示顺序与源顺序不同，indexInParent 就不再等于显示位置；
 *  - 让渲染层现算要么 O(兄弟数)（20 万项数组下每行都要扫一遍，滚动直接卡死），
 *    要么再查一张反查表。摊平的时候顺手记一个比特是最省的。
 *
 * 为什么不用标记对象：每行多一次分配（36 万行就是 36 万个对象、十几 MB 垃圾），
 * 而 kinds 每个元素只是一个 smi，V8 里 8 字节。节点自己的 depth / type /
 * keyNode / parent 都已经挂在节点上（见 json-parser.js 的惰性树），不必再复制。
 *
 * ## 为什么不做递归树结构
 *
 * 曾经考虑过 rope / 段树（只物化访问到的分支）。对「光标停在文档开头」的场景
 * 它更省，但要实现 O(log n) 的下标定位，复杂度和边界情况都明显上升。
 * 实测表明扁平表的插入/删除是数组 memmove 级别，32 万行约 1ms、线性查找约 4ms，
 * 都在一帧预算内，所以先选简单且可验证的扁平表。
 * 真需要 100MB+ 时再换 rope，届时本模块的 API 不用变。
 *
 * ## 实现上的两个坑（都已在代码里避开）
 *
 * 1. `Array.prototype.splice.apply(rows, [pos, 0].concat(kids))` 在 kids 有几万项
 *    时会因为实参个数超限直接抛 RangeError（V8 的 apply 实参上限约 6~12 万），
 *    所以插入改用「切片 + concat」。删除用 `splice(pos, count)`（两个数值实参，
 *    没有上限问题，且是 O(n) memmove）。
 * 2. 遍历一律用显式栈而不是递归：JSON 嵌套可以很深（几千层），递归遍历既会爆栈，
 *    也没法在一个函数里安全地处理「先开后闭」的顺序。折叠时也不做递归求和，
 *    改成向前找本节点的闭行下标——同样是 O(子树)，但没有栈深度风险。
 */
(function () {
  'use strict';

  var NS = (globalThis.__EDGE_JSON_FORMATTER__ =
    globalThis.__EDGE_JSON_FORMATTER__ || {});

  /* kinds 的两个比特 */
  var CLOSE_BIT = 1;    // 1 = 闭行（容器的 `}`、`]`）
  var LAST_BIT = 2;     // 1 = 最后一个兄弟（行尾要补逗号）

  /* 显式栈里的「相位」：与 kinds 复用同一套比特，压栈时顺手带上 LAST_BIT */
  var PH_CLOSE = CLOSE_BIT;

  /** 容器判断：与 json-parser.js 的节点类型保持一致 */
  function isContainer(node) {
    return node.type === 'object' || node.type === 'array';
  }

  function isCloseKind(k) { return (k & CLOSE_BIT) === CLOSE_BIT; }
  function isLastKind(k) { return (k & LAST_BIT) === LAST_BIT; }

  /** 默认子节点取值器（不排序、按源顺序） */
  function defaultAccess() {
    return {
      count: function (node) {
        if (node.type === 'object') return node.entries.length;
        if (node.type === 'array') return node.items.length;
        return 0;
      },
      child: function (node, i) {
        if (node.type === 'object') return node.entries[i].value;
        return node.items[i];
      }
    };
  }

  var DEFAULT_ACCESS = defaultAccess();

  /**
   * 非空容器 = 展开后有子行、需要一个闭行的那种。
   * @param {object} node
   * @param {object} [acc] 子节点取值器（默认按源顺序）
   */
  function isBranch(node, acc) {
    if (!isContainer(node)) return false;
    return (acc || DEFAULT_ACCESS).count(node) > 0;
  }

  /** 默认取值器下的子节点个数，给单测/外部用 */
  function childCount(node) {
    return DEFAULT_ACCESS.count(node);
  }

  /**
   * 把一棵子树的「当前可见行」按文档序追加到 out / kinds。
   *
   * 可见 = 自己这一行（+ 容器的话再加一行闭行），以及「已展开容器」的递归子行。
   * 折叠的容器只贡献自己那两行——所以用户折叠起来的分支完全不占用行表，
   * 也不会去物化它的后代。
   *
   * 用显式栈而不是递归，栈里交错压入 `节点, 相位`：
   * 压入顺序是「先闭相位、后子节点」，于是子节点先被处理、闭行最后补上，
   * 正好得到 前序 + 闭行收尾 的文档序。相位里带着「最后一个兄弟」比特，
   * 这样闭行也记得自己要不要补逗号。
   *
   * @param {object} root 子树根
   * @param {Array} out 节点序列（追加写）
   * @param {Array} kinds 行类型序列（追加写）
   * @param {object} [acc] 子节点取值器
   * @param {boolean} [isLast] 这棵子树是不是父容器的最后一个子项（决定末尾逗号）
   */
  function collect(root, out, kinds, acc, isLast) {
    var stack = [root, isLast === false ? 0 : LAST_BIT];
    while (stack.length) {
      var ph = stack.pop();
      var node = stack.pop();
      if ((ph & CLOSE_BIT) === CLOSE_BIT) {
        out.push(node);
        kinds.push(ph);
        continue;
      }
      out.push(node);
      kinds.push(ph);
      if (!isBranch(node, acc)) continue;
      stack.push(node, ph | CLOSE_BIT);
      if (!node.expanded) continue;
      var n = acc.count(node);
      for (var i = n - 1; i >= 0; i--) {
        stack.push(acc.child(node, i), i === n - 1 ? LAST_BIT : 0);
      }
    }
  }

  /**
   * 子树贡献的可见行数（含自身的开行与闭行）。
   * 折叠时不再走这里（改成找闭行下标，见 collapse），保留给单测当「全量重建」
   * 的对照实现。刻意写成迭代版，避免深嵌套爆栈。
   */
  function subtreeRows(node, acc) {
    var a = acc || DEFAULT_ACCESS;
    var total = 0;
    var stack = [node, LAST_BIT];
    while (stack.length) {
      var ph = stack.pop();
      var n = stack.pop();
      total++;
      if ((ph & CLOSE_BIT) === CLOSE_BIT) continue;
      if (!isBranch(n, a)) continue;
      stack.push(n, ph | CLOSE_BIT);
      if (!n.expanded) continue;
      var c = a.count(n);
      for (var i = c - 1; i >= 0; i--) {
        stack.push(a.child(n, i), i === c - 1 ? LAST_BIT : 0);
      }
    }
    return total;
  }

  /**
   * 建行模型。
   * @param {object} root 惰性树的根节点
   * @param {object} [access] 子节点取值器 {count, child}。默认按源顺序；
   *        传自定义实现即可让行表按别的顺序摊平（查看器的「按键排序」走这条）。
   * @returns {object} 行模型
   */
  function createRowModel(root, access) {
    var acc = access || DEFAULT_ACCESS;
    /** 行 → 节点引用 */
    var rows = [];
    /** 行 → 开行/闭行 + 是否最后一个兄弟 */
    var kinds = [];

    function rebuild() {
      rows = [];
      kinds = [];
      collect(root, rows, kinds, acc);
      return rows.length;
    }

    rebuild();

    /**
     * 节点开行当前在第几行。线性查找，36 万行实测约 4~6ms —— 够用但吃掉小半帧
     * 预算，所以对外接口都带 hint：渲染层本来就知道每一行渲染的是哪个下标
     * （窗口是 [first, last)），点击折叠时把那个下标传进来即可 O(1) 命中。
     * 不做「节点 → 行」的反查表：那种表每次插入/删除都要整体平移，
     * 36 万项的 Map 更新要几十毫秒，比线性查找更慢。
     */
    function indexOf(node) {
      for (var i = 0; i < rows.length; i++) {
        if (rows[i] === node && !isCloseKind(kinds[i])) return i;
      }
      return -1;
    }

    /** 带提示的定位：提示命中就是 O(1)，不命中原样退回线性查找 */
    function locate(node, hint) {
      if (typeof hint === 'number' && hint >= 0 && hint < rows.length &&
          rows[hint] === node && !isCloseKind(kinds[hint])) {
        return hint;
      }
      return indexOf(node);
    }

    /**
     * 在第 pos 行处插入一整段行。
     * 不用 splice.apply（实参个数上限），走「尾部切片 + concat」。
     */
    function insertRows(pos, kn, kk) {
      if (!kn.length) return;
      var tailN = rows.slice(pos);
      var tailK = kinds.slice(pos);
      rows.length = pos;
      kinds.length = pos;
      rows = rows.concat(kn, tailN);
      kinds = kinds.concat(kk, tailK);
    }

    /** 展开一个容器：把它的可见子树整段插入到它这一行之后 */
    function expand(node, hint) {
      if (!isBranch(node, acc) || node.expanded) return null;
      var at = locate(node, hint);
      if (at < 0) return null;                    // 折叠在别的分支里，不在行表上
      node.expanded = true;

      var kn = [];
      var kk = [];
      var n = acc.count(node);
      // 直接往同一对数组里追加：不用中间数组再合并，既省内存也避开
      // 「几万个实参的 push.apply」这个上限坑
      for (var i = 0; i < n; i++) {
        collect(acc.child(node, i), kn, kk, acc, i === n - 1);
      }
      if (!kn.length) return { at: at, added: 0 };
      insertRows(at + 1, kn, kk);
      return { at: at, added: kn.length };
    }

    /**
     * 折叠一个容器：把它子树占用的可见行整段移除。
     *
     * 行数不靠递归求和，而是往前找本节点的闭行：同一个节点在行表里只会出现
     * 一次闭行，且它一定紧跟在自己子树的末尾，所以「at 之后第一个
     * rows[i] === node 且是闭行」就是它。
     */
    function collapse(node, hint) {
      if (!isBranch(node, acc) || !node.expanded) return null;
      var at = locate(node, hint);
      if (at < 0) return null;

      var closeAt = -1;
      for (var i = at + 1; i < rows.length; i++) {
        if (rows[i] === node && isCloseKind(kinds[i])) { closeAt = i; break; }
      }
      var count = closeAt - at - 1;
      node.expanded = false;
      if (count <= 0) return { at: at, removed: 0 };

      rows.splice(at + 1, count);
      kinds.splice(at + 1, count);
      return { at: at, removed: count };
    }

    function setExpanded(node, on, hint) {
      return on ? expand(node, hint) : collapse(node, hint);
    }

    /**
     * 节点的标准路径，与解析器的 joinKey 语义一致（数组用 [i]，对象用 .key）。
     * 从 parent 链往上走——节点自带 parent / indexInParent，不必额外维护。
     * 对象一律用键名，所以「按键排序」改变显示顺序也不会写错路径。
     */
    function pathOf(node) {
      var keys = [];
      var cur = node;
      while (cur && cur.parent) {
        if (cur.parent.type === 'array') keys.push('[' + cur.indexInParent + ']');
        else if (cur.keyNode) keys.push(NS.parser.joinKey('', cur.keyNode.value));
        cur = cur.parent;
      }
      var out = '$';
      for (var i = keys.length - 1; i >= 0; i--) out += keys[i];
      return out;
    }

    /**
     * 取渲染窗口：只把 [from, to) 这段行交给 DOM。
     * 返回新数组（元素是 {node, close, last}），避免调用方持有内部表后又被改掉。
     */
    function windowRows(from, to) {
      if (from < 0) from = 0;
      if (to > rows.length) to = rows.length;
      var list = [];
      for (var i = from; i < to; i++) {
        list.push({ node: rows[i], close: isCloseKind(kinds[i]),
                    last: isLastKind(kinds[i]) });
      }
      return list;
    }

    return {
      get length() { return rows.length; },
      rebuild: rebuild,
      nodeAt: function (i) { return rows[i]; },
      isClose: function (i) { return isCloseKind(kinds[i]); },
      isLast: function (i) { return isLastKind(kinds[i]); },
      indexOf: indexOf,
      locate: locate,
      expand: expand,
      collapse: collapse,
      setExpanded: setExpanded,
      pathOf: pathOf,
      windowRows: windowRows,
      /** 供调试/测试：拿到内部行表（每次调用返回当前那份，插入后会整体换新） */
      allRows: function () { return rows; },
      allKinds: function () { return kinds; }
    };
  }

  NS.rowModel = {
    create: createRowModel,
    // 内部工具也导出，便于单测与将来的 rope 改造复用
    isContainer: isContainer,
    isBranch: isBranch,
    childCount: childCount,
    subtreeRows: subtreeRows,
    isCloseKind: isCloseKind,
    isLastKind: isLastKind,
    CLOSE_BIT: CLOSE_BIT,
    LAST_BIT: LAST_BIT
  };
})();
