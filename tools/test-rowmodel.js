/**
 * 行模型单测 + 性能实测。
 *
 * 运行：node --expose-gc tools/test-rowmodel.js
 *
 * 核心不变式：**增量维护（expand/collapse 就地插删）的结果必须与全量重建一致**
 * ——行序列与行类型（开行/闭行）两条都要一致。扁平表最容易出错的地方就是这里
 * （插错位置、少删一段、闭行错位、折叠分支仍留在表上），所以每次增删后都拿一份
 * 独立实现的摊平结果做比对。
 */
'use strict';
const fs = require('fs');
const path = require('path');

const base = path.join(__dirname, '..');
const g = {};
for (const f of ['src/shared/defaults.js', 'src/content/json-parser.js',
                 'src/content/rowmodel.js']) {
  new Function('globalThis', fs.readFileSync(path.join(base, f), 'utf8'))(g);
}
const NS = g.__EDGE_JSON_FORMATTER__;
const parser = NS.parser;
const rowModel = NS.rowModel;

let fails = 0;
function check(name, ok, extra) {
  console.log('  [' + (ok ? 'PASS' : 'FAIL') + '] ' + name + (extra ? '  ' + extra : ''));
  if (!ok) fails++;
}
function mb(n) { return (n / 1048576).toFixed(1) + ' MB'; }
function gc() { if (global.gc) { global.gc(); global.gc(); } }
function heap() { gc(); return process.memoryUsage().heapUsed; }

function isC(n) { return n.type === 'object' || n.type === 'array'; }
function kidsOf(n) { return n.type === 'object' ? n.entries : n.items; }
function kidAt(n, i) { return n.type === 'object' ? n.entries[i].value : n.items[i]; }
function branch(n) { return isC(n) && kidsOf(n).length > 0; }

/**
 * 独立的摊平实现（不变式的参照），故意不复用 rowmodel 的代码。
 * 同时吐出节点序列与行类型序列（bit0 闭行 / bit1 最后一个兄弟）。
 */
function flatten(node, out, kinds, last) {
  const L = last === false ? 0 : 2;
  out.push(node); kinds.push(L);
  if (branch(node)) {
    if (node.expanded) {
      const n = kidsOf(node).length;
      for (let i = 0; i < n; i++) flatten(kidAt(node, i), out, kinds, i === n - 1);
    }
    out.push(node); kinds.push(L | 1);
  }
  return out;
}

/** 收集所有节点（含容器与叶子） */
function allNodes(root) {
  const out = [];
  parser.walk(root, (n) => out.push(n));
  return out;
}

/** 全部折叠 / 全部展开 */
function setAll(root, on) {
  for (const n of allNodes(root)) {
    if (isC(n)) n.expanded = !!on;
  }
}

function sameSeq(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// ---------------------------------------------------------------- 1) 正确性

console.log('=== 1) 小结构上的正确性（增量维护 == 全量重建）===');
{
  const text = JSON.stringify({
    a: 1,
    b: { c: [1, 2, 3], d: { e: true, f: null } },
    g: [{ h: 1, i: 2 }, { j: [3, 4] }],
    k: 'x'
  }, null, 2);
  const res = parser.parse(text);
  setAll(res.root, false);                       // 从「全折叠」开始，逐级手动展开

  const model = rowModel.create(res.root);

  const oracle = () => {
    const o = [], k = [];
    flatten(res.root, o, k);
    return { o, k };
  };
  const verify = (label) => {
    const { o, k } = oracle();
    const okRows = sameSeq(model.allRows(), o);
    const okKinds = sameSeq(model.allKinds(), k);
    check(label + '：行表与全量重建一致', okRows && okKinds,
          'model=' + model.length + ' oracle=' + o.length +
          (okRows ? '' : ' [行序列不符]') + (okKinds ? '' : ' [行类型不符]'));
    return okRows && okKinds;
  };

  verify('初始（全折叠）');
  check('全折叠的非空根占两行（开 + 闭）', model.length === 2, 'length=' + model.length);
  check('第 0 行是开行、第 1 行是闭行',
        model.isClose(0) === false && model.isClose(1) === true);

  const conts = allNodes(res.root).filter(isC);
  const byPath = (p) => conts.find((n) => model.pathOf(n) === p);

  const root = res.root;
  model.expand(root);
  verify('展开根');
  check('根展开后 = 根开行 + a/b/g/k 四行 + 根闭行（b、g 各占两行）',
        model.nodeAt(0) === root && model.length === 8, 'length=' + model.length);

  const b = byPath('$.b');
  model.expand(b);
  verify('展开 $.b');

  const bc = byPath('$.b.c');
  model.expand(bc);
  verify('展开 $.b.c（数组）');
  check('$.b.c 的 3 个元素各 1 行',
        model.indexOf(bc) >= 0 && model.allRows().filter((n) => n.parent === bc).length === 3);
  check('indexOf 命中的是开行而不是闭行',
        model.allKinds()[model.indexOf(bc)] === 0);

  const bg = byPath('$.g');
  model.expand(bg);
  verify('展开 $.g（数组含 2 个对象，对象仍折叠 → 各两行）');

  const g0 = byPath('$.g[0]');
  model.expand(g0);
  verify('展开 $.g[0]');

  // 关键回归点：折叠一个「内部还有已展开分支」的容器，必须整段移除（含闭行）
  const g1 = byPath('$.g[1]');
  model.collapse(bg);
  verify('折叠 $.g（内部含已展开的 $.g[0]，须整段移除）');
  check('折叠后 $.g 的后代全部离表',
        !model.allRows().includes(g0) && !model.allRows().includes(g1));
  check('折叠不该误伤兄弟分支（$.b.c 仍在表上）',
        model.allRows().includes(bc) && model.allRows().includes(byPath('$.b.d')));

  model.expand(bg);
  verify('再次展开 $.g（$.g[0] 仍是展开态，应恢复）');
  check('重新展开后 $.g[0] 的后代回来了',
        model.allRows().includes(g0) && model.indexOf(g0) > 0);

  // 路径还原
  check('pathOf 还原对象键路径', model.pathOf(byPath('$.b.d')) === '$.b.d',
        model.pathOf(byPath('$.b.d')));
  check('pathOf 还原数组下标路径', model.pathOf(g0) === '$.g[0]', model.pathOf(g0));
  check('pathOf 还原嵌套路径', model.pathOf(byPath('$.b.c')) === '$.b.c',
        model.pathOf(byPath('$.b.c')));

  // 窗口切片
  const win = model.windowRows(1, 3);
  check('windowRows 取到正确的两行（含 close 标记）',
        win.length === 2 && win[0].node === model.nodeAt(1) &&
        win[0].close === model.isClose(1) && win[1].node === model.nodeAt(2));
  check('windowRows 越界不报错', model.windowRows(-5, 99999).length === model.length);

  // 空容器（{} / []）只占一行，没有闭行，也不能展开
  const empty = parser.parse(JSON.stringify({ e: {}, arr: [], s: 'x' }));
  setAll(empty.root, false);
  const em = rowModel.create(empty.root);
  em.expand(empty.root);
  const emptyObj = allNodes(empty.root).find((n) => n.type === 'object' && n !== empty.root);
  check('空容器只占一行、没有闭行（根开 + e/arr/s + 根闭 = 5 行）',
        em.length === 5, 'length=' + em.length);
  const atE = em.indexOf(emptyObj);
  check('空容器行之后不是闭行', em.isClose(atE + 1) === false, 'next kind=' + em.allKinds()[atE + 1]);
  check('对空容器 expand 返回 null 且行数不变',
        em.expand(emptyObj) === null && em.length === 5);

  // 重复展开/折叠要幂等
  model.expand(bg);
  model.collapse(bg);
  const after1 = model.length;
  model.collapse(bg);                            // 已折叠，再折叠应是空操作
  check('对已展开的再展开 / 对已折叠的再折叠都是空操作',
        model.length === after1, 'length=' + model.length);
  verify('幂等操作后仍一致');

  /* expand 只插入「子行」——节点自己的开行/闭行本来就在表上。
     所以新增行数 = 子树的子行数，不能拿 subtreeRows（含自身两行）直接比。
     用独立的摊平实现算这个数，同时把导出的 subtreeRows 也对一遍。 */
  const bg2 = byPath('$.g');
  const kidsRowCount = (n) => {
    const o = [], k = [];
    const m = kidsOf(n).length;
    for (let i = 0; i < m; i++) flatten(kidAt(n, i), o, k);
    return o.length;
  };
  const expectedAdded = kidsRowCount(bg2);       // 折叠态下先算，与 node.expanded 无关
  const beforeLen = model.length;
  const r = model.expand(bg2);
  check('expand 新增行数 = 子行数（独立实现）',
        r.added === expectedAdded && model.length === beforeLen + expectedAdded,
        'expected=' + expectedAdded + ' added=' + r.added);
  check('subtreeRows = 自身两行 + 子行数',
        rowModel.subtreeRows(bg2) === 2 + expectedAdded,
        'subtreeRows=' + rowModel.subtreeRows(bg2));
  verify('展开后仍与全量重建一致');
}

// ------------------------------------------------- 2) 随机增删的压力测试

console.log('\n=== 2) 随机增删 300 次，每次都和全量重建比对 ===');
{
  const text = JSON.stringify({
    users: Array.from({ length: 40 }, (_, i) => ({
      id: i, name: 'n' + i, tags: ['a', 'b'], meta: { ok: i % 2 === 0, deep: { v: i } }
    })),
    tail: { x: 1 }
  }, null, 2);
  const res = parser.parse(text);
  setAll(res.root, false);

  const model = rowModel.create(res.root);
  const conts = allNodes(res.root).filter(isC);
  model.expand(res.root);

  let seed = 42;
  const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;

  let mismatch = 0, kindMismatch = 0, ops = 0;
  for (let i = 0; i < 300; i++) {
    const n = conts[Math.floor(rnd() * conts.length)];
    const on = rnd() < 0.55;
    if (n.expanded === on) continue;
    model.setExpanded(n, on);
    ops++;
    const o = [], k = [];
    flatten(res.root, o, k);
    if (!sameSeq(model.allRows(), o)) mismatch++;
    else if (!sameSeq(model.allKinds(), k)) kindMismatch++;
  }
  check('300 次随机展开/折叠后行表始终与全量重建一致',
        mismatch === 0 && kindMismatch === 0,
        '实际执行 ' + ops + ' 次，行序列不一致 ' + mismatch + ' 次，行类型不一致 ' + kindMismatch + ' 次');
  check('最终行数合理', model.length > 1, 'length=' + model.length);
}

// ------------------------------------- 3) 超大单次插入（apply 实参上限回归）

console.log('\n=== 3) 超大单次插入：一次展开 15 万项（防 splice.apply 实参超限）===');
{
  const items = [];
  for (let i = 0; i < 150000; i++) items.push({ id: i, name: 'n' + i });
  const res = parser.parse(JSON.stringify({ big: items }));
  setAll(res.root, false);
  const model = rowModel.create(res.root);
  model.expand(res.root);                        // 展开根 → 露出 $.big（仍折叠）

  const big = model.allRows().find((n) => n.keyNode && n.keyNode.value === 'big');
  let err = null;
  const t0 = process.hrtime.bigint();
  try {
    model.expand(big);                           // 15 万个对象 × 2 行 = 30 万行一次插入
  } catch (e) { err = e; }
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  check('一次插入 30 万行不抛异常', !err, err ? String(err.message) : '');
  check('插入后行数与全量重建一致',
        !err && sameSeq(model.allRows(), flatten(res.root, [], [])),
        'length=' + model.length);

  const t1 = process.hrtime.bigint();
  model.collapse(big);
  const ms2 = Number(process.hrtime.bigint() - t1) / 1e6;
  check('反向折叠回去行数与全量重建一致',
        sameSeq(model.allRows(), flatten(res.root, [], [])), 'length=' + model.length);
  console.log('  展开 ' + ms.toFixed(1) + ' ms  折叠 ' + ms2.toFixed(1) + ' ms');
  // 这条守的是两件事：① insertRows 不再走 splice.apply（30 万实参会抛 RangeError，
  // 真出问题会直接抛、整段测试就挂了）；② 插入/删除是数组 memmove 级别的线性操作，
  // 不是 O(n²)。门槛给到 600ms：退化成平方级是秒级以上，而冷启动 JIT 未预热时
  // 线性路径实测 130ms 上下浮动，卡 150ms 会偶发误报。
  check('单次 30 万行插/删 < 600ms（守 RangeError 与平方级退化）',
        ms < 600 && ms2 < 600,
        ms.toFixed(1) + ' / ' + ms2.toFixed(1) + ' ms');
}

// ------------------------------------------------------- 4) 22MB 实测

console.log('\n=== 4) 22MB 文档实测 ===');
{
  const file = path.join(__dirname, 'fixtures', 'big-20mb.json');
  const text = fs.readFileSync(file, 'utf8');
  console.log('  文件 ' + path.basename(file) + '  ' + mb(text.length) + '  ' +
              text.split('\n').length.toLocaleString() + ' 行');

  const h0 = heap();
  const t0 = process.hrtime.bigint();
  const res = parser.parse(text);
  const t1 = process.hrtime.bigint();
  const parseMs = Number(t1 - t0) / 1e6;
  const h1 = heap();
  console.log('  parse()            ' + parseMs.toFixed(1) + ' ms    堆净增 ' + mb(h1 - h0));

  // 全折叠：是否真的只物化根
  setAll(res.root, false);
  const t2 = process.hrtime.bigint();
  const model = rowModel.create(res.root);
  const t3 = process.hrtime.bigint();
  console.log('  建模型（全折叠）    ' + (Number(t3 - t2) / 1e6).toFixed(1) +
              ' ms    行数 ' + model.length);

  // 全展开：这是最坏情况
  const t4 = process.hrtime.bigint();
  setAll(res.root, true);
  model.rebuild();
  const t5 = process.hrtime.bigint();
  const h2 = heap();
  const expandMs = Number(t5 - t4) / 1e6;
  console.log('  全展开 + 重建      ' + expandMs.toFixed(1) + ' ms    行数 ' +
              model.length.toLocaleString() +
              '    堆净增 ' + mb(h2 - h1) + '（含把整棵树物化出来）');
  check('全展开行数 > 30 万', model.length > 300000, model.length.toLocaleString());

  /*
   * 行表本身的净开销必须**隔离测量**：上面那次净增里绝大部分是把几十万个节点
   * 物化出来的成本（惰性树的节点对象），不能算到行表头上。
   *
   * 注意别用「同一个模型 rebuild 两次再求差」——rebuild 复用同一个数组，
   * V8 保留后备存储，那次差值是 0，量到的是个空操作。要新建 N 份行表。
   */
  const N = 5;
  const beforeTable = heap();
  const copies = [];
  for (let k = 0; k < N; k++) copies.push(rowModel.create(res.root));
  const afterTable = heap();
  const totalRows = copies.reduce((s, m) => s + m.length, 0);
  const perRow = (afterTable - beforeTable) / totalRows;
  console.log('  行表净开销          ' + mb(afterTable - beforeTable) + ' / ' +
              totalRows.toLocaleString() + ' 行  →  ' + perRow.toFixed(1) + ' B/行' +
              '   （每行一个 JS 对象约 500 B/行）');
  check('每行开销远小于对象数组（< 32 B/行）', perRow < 32, perRow.toFixed(1) + ' B/行');
  check('单份行表总开销 < 8MB（32 万行）',
        (afterTable - beforeTable) / N < 8 * 1048576,
        mb((afterTable - beforeTable) / N));
  copies.length = 0;

  // 随机滚动定位：窗口取数 + 线性查找
  const t6 = process.hrtime.bigint();
  let acc = 0;
  for (let i = 0; i < 2000; i++) {
    const from = Math.floor((i / 2000) * (model.length - 50));
    acc += model.windowRows(from, from + 50).length;
  }
  const t7 = process.hrtime.bigint();
  const winMs = Number(t7 - t6) / 1e6;
  console.log('  取 2000 次 50 行窗口 ' + winMs.toFixed(1) + ' ms（' +
              (winMs / 2000).toFixed(3) + ' ms/次）');
  check('单次窗口取数 < 0.5ms', winMs / 2000 < 0.5, (winMs / 2000).toFixed(3) + ' ms');
  check('窗口总数正确', acc === 2000 * 50, String(acc));

  const t8 = process.hrtime.bigint();
  const target = model.nodeAt(model.length >> 1);
  const idx = model.indexOf(target);
  const t9 = process.hrtime.bigint();
  const findMs = Number(t9 - t8) / 1e6;
  console.log('  indexOf 线性扫描    ' + findMs.toFixed(2) + ' ms  命中 ' + idx);
  check('indexOf 命中（跳过闭行）', idx >= 0 && model.isClose(idx) === false, String(idx));

  /* 交互式折叠走的是带 hint 的路径：渲染层本来就知道那一行是第几行。
     这条路径必须是 O(1)，否则 32 万行下每次点折叠都要花掉半帧。
     提示只对「开行」有效——闭行本来就不可交互，落到线性查找也无所谓。 */
  const t10 = process.hrtime.bigint();
  let hits = 0, tried = 0;
  for (let i = 0; i < 1000; i++) {
    const at = (i * 313) % model.length;
    if (model.isClose(at)) continue;
    tried++;
    if (model.locate(model.nodeAt(at), at) === at) hits++;
  }
  const t11 = process.hrtime.bigint();
  const hintMs = Number(t11 - t10) / 1e6;
  console.log('  带 hint 定位 ×' + tried + '   ' + hintMs.toFixed(2) + ' ms（' +
              (hintMs / tried).toFixed(4) + ' ms/次）');
  check('带 hint 定位命中率 100%', hits === tried, hits + '/' + tried);
  check('单次带 hint 定位 < 0.01ms', hintMs / tried < 0.01,
        (hintMs / tried).toFixed(4) + ' ms');
}

console.log('\n' + '='.repeat(52));
if (fails) {
  console.log('[失败] ' + fails + ' 项');
  process.exit(1);
}
console.log('[通过] 行模型正确性与性能均达标');
