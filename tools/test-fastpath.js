/**
 * 快路径（原生 JSON.parse + 惰性树）专项测试。
 *
 * 快路径只在文本 >= 256KB 时启用，所以这里的用例都会把样本撑过阈值，
 * 并用 noFastPath:true 跑手写解析器做逐节点对照，保证两条路径产出一致。
 *
 * 判定「走没走快路径」看根的 __sess（惰性会话）是否存在：
 * 有 = 走了原生解析 + 惰性树，没有 = 退回了手写解析器。
 *
 * 运行：node tools/test-fastpath.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

const base = path.join(__dirname, '..');
/* 用 new Function 而不是 vm 沙箱加载源码：vm 里的全局对象是 context 代理，
   Object.keys / Array.isArray 这类逐节点高频调用会被拖慢好几倍，
   性能用例的数字会严重失真（扩展真实跑在页面上下文，不是沙箱）。 */
const fakeGlobal = {};
for (const file of [
  'src/shared/defaults.js',
  'src/content/json-parser.js'
]) {
  new Function('globalThis', fs.readFileSync(path.join(base, file), 'utf8'))(fakeGlobal);
}
const parser = fakeGlobal.__EDGE_JSON_FORMATTER__.parser;

let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log('  [PASS] ' + name + (extra ? '  ' + extra : '')); }
  else { fail++; console.log('  [FAIL] ' + name + (extra ? '  ' + extra : '')); }
}
const usedFastPath = res => !!(res && res.root && res.root.__sess);

/* 生成 >256KB 的样本：覆盖规范转义（\" \\ \n \t）、非 ASCII、数字、空容器、嵌套。
   刻意不用 \uXXXX：那种转义会让快路径按设计退回手写解析器（见用例 4）。 */
function makeBig(n) {
  const items = [];
  for (let i = 0; i < n; i++) {
    items.push({
      id: i,
      name: '条目-' + i,
      note: '带"引号"、反斜杠\\、换行\n、制表\t 与中文-' + i,
      unicode: '\u00e9\u4e2d\ud83d\ude00',
      price: i * 1.5,
      qty: i,
      ok: i % 2 === 0,
      tag: null,
      emptyObj: {},
      emptyArr: [],
      nested: { deep: { deeper: [i, i + 1, 'x'] } }
    });
  }
  return JSON.stringify({ list: items, meta: { total: n } }, null, 2);
}

/** 逐节点对比两棵树（忽略 id/parent/path/indexInParent/start/end） */
function sameTree(a, b) {
  if (!a || !b) return !!a && !!b;
  if (a.type !== b.type) return false;
  if (a.type === 'object') {
    if (a.entries.length !== b.entries.length) return false;
    for (let i = 0; i < a.entries.length; i++) {
      if (a.entries[i].keyNode.value !== b.entries[i].keyNode.value) return false;
      if (!sameTree(a.entries[i].value, b.entries[i].value)) return false;
    }
    return true;
  }
  if (a.type === 'array') {
    if (a.items.length !== b.items.length) return false;
    for (let j = 0; j < a.items.length; j++) if (!sameTree(a.items[j], b.items[j])) return false;
    return true;
  }
  // 基本类型：值必须一致。raw 也要一致——字符串是转义写法、数字是书写形式。
  // （容器的 raw 不做比较：惰性树不保留容器的原文切片，查看器也从不读它）
  if (a.value !== b.value) return false;
  if (a.raw !== b.raw) return false;
  return true;
}

/** 全树展开遍历（顺带验证惰性视图能被完整物化）。键也算节点，与解析器口径一致 */
function walkAll(node, visit) {
  visit(node);
  if (node.type === 'object') {
    for (let i = 0; i < node.entries.length; i++) {
      walkAll(node.entries[i].keyNode, visit);
      walkAll(node.entries[i].value, visit);
    }
  } else if (node.type === 'array') {
    for (let j = 0; j < node.items.length; j++) walkAll(node.items[j], visit);
  }
}

function run() {
  console.log('=== 快路径（原生 JSON.parse + 惰性树）专项测试 ===\n');

  // 1. 大样本：快路径 vs 手写解析器，逐节点一致
  const big = makeBig(2600);   // ≈ 500KB
  check('样本超过快路径阈值', big.length >= 256 * 1024, (big.length / 1024).toFixed(0) + 'KB');

  const fast = parser.parse(big);
  const slow = parser.parse(big, { noFastPath: true });
  check('样本确实走了快路径', usedFastPath(fast));
  check('快路径与手写解析器树一致', sameTree(fast.root, slow.root));
  check('节点数一致', fast.count === slow.count, fast.count + ' vs ' + slow.count);
  check('深度一致', fast.depth === slow.depth, fast.depth + ' vs ' + slow.depth);
  check('快路径未误报宽松解析', fast.lenient === false && slow.lenient === false);

  // 2. 惰性：未渲染的子树不物化；物化后与手写解析器一致
  const fresh = parser.parse(big);           // 单独取一棵没被访问过的树
  check('访问 entries 前没有物化任何子节点',
    (fresh.root.__kid === null || fresh.root.__kid === undefined) &&
    fresh.root.__sess.nodes.length === 1,
    '会话里只有根节点');
  const listNode = fast.root.entries[0].value;
  check('按需物化：拿到 list 节点', listNode.type === 'array' && listNode.items.length === 2600);
  check('只物化访问到的分支（会话节点数远小于总节点数）',
    fresh.root.__sess.nodes.length === 1 && (() => {
      const one = parser.parse(big);
      one.root.entries[0].value.items[3];     // 只碰一条分支
      return one.root.__sess.nodes.length < 12;
    })(),
    '取完一条分支后仍 < 12 个容器');
  const probe = listNode.items[3].entries[2].value;      // note 字段
  const probeSlow = slow.root.entries[0].value.items[3].entries[2].value;
  check('规范转义（\\" \\\\ \\n \\t）的 raw 与原文一致', probe.raw === probeSlow.raw,
    JSON.stringify(probe.raw).slice(0, 50));
  check('非 ASCII 字符的 raw 一致', listNode.items[3].entries[3].value.raw ===
    slow.root.entries[0].value.items[3].entries[3].value.raw);
  check('数字 raw 一致', listNode.items[7].entries[4].value.raw ===
    slow.root.entries[0].value.items[7].entries[4].value.raw);
  check('keyNode.raw 一致', listNode.items[5].entries[0].keyNode.raw ===
    slow.root.entries[0].value.items[5].entries[0].keyNode.raw);

  // 3. 惰性数组视图的数组语义（查看器/测试都按数组用）
  check('length 是真实长度', listNode.items.length === 2600);
  check('slice 可用', listNode.items.slice(0, 3).length === 3);
  check('filter/map 可用',
    fast.root.entries.filter(e => e.keyNode.value === 'meta').length === 1 &&
    fast.root.entries.map(e => e.keyNode.value).join(',') === 'list,meta');
  check('for...of 可用', (() => {
    let c = 0;
    for (const it of listNode.items) { if (c++ > 2) break; }
    return c === 4;
  })());

  // 4. \uXXXX 守卫：原文无法还原，必须退回手写解析器
  const uniDoc = '{"pad":"' + 'x'.repeat(300 * 1024) + '","s":"\\u4e2d\\u6587","n":1}';
  const uFast = parser.parse(uniDoc);
  const uSlow = parser.parse(uniDoc, { noFastPath: true });
  check('含 \\uXXXX 时退回手写解析器', !usedFastPath(uFast));
  check('退回后 raw 保住源码原文',
    uFast.root.entries[1].value.raw === '"\\u4e2d\\u6587"',
    uFast.root.entries[1].value.raw);

  // 5. 大整数守卫：字符串外的 16+ 位数字会丢精度，必须退回
  let idDoc = '{"list":[';
  for (let i = 0; i < 8000; i++) idDoc += (i ? ',' : '') + '{"orderId":60065383650751692' + (i % 10) + '}';
  idDoc += '],"pad":"' + 'x'.repeat(300 * 1024) + '"}';
  const iFast = parser.parse(idDoc);
  const iSlow = parser.parse(idDoc, { noFastPath: true });
  check('含字符串外 16+ 位整数时退回手写解析器', !usedFastPath(iFast));
  check('大整数 raw 保住原文',
    iFast.root.entries[0].value.items[0].entries[0].value.raw === '600653836507516920',
    iFast.root.entries[0].value.items[0].entries[0].value.raw);
  check('大整数两条路径 raw 一致',
    iFast.root.entries[0].value.items[0].entries[0].value.raw ===
    iSlow.root.entries[0].value.items[0].entries[0].value.raw);
  // 反过来：16 位数字放在字符串里不构成风险，应当走快路径
  let okDoc = '{"list":[' + Array.from({ length: 12000 }, (_, i) => '{"id":"60065383650751692' + (i % 10) + '"}').join(',') + ']}';
  check('字符串里的 16 位数字不触发退回', usedFastPath(parser.parse(okDoc)),
    (okDoc.length / 1024).toFixed(0) + 'KB');

  // 6. 数字开头的键：会被引擎重排，必须退回手写解析器保住原文键序。
  //    样本必须手拼 JSON 字符串——JSON.stringify 会提前把数字键排到最前。
  let rawDoc = '{"z":1,"2":2,"a":3';
  for (let i = 0; i < 30000; i++) rawDoc += ',"k' + i + '":' + i;
  rawDoc += '}';
  const kFast = parser.parse(rawDoc);
  const kSlow = parser.parse(rawDoc, { noFastPath: true });
  const ko = f => f.root.entries.slice(0, 3).map(e => e.keyNode.value).join(',');
  check('数字开头键退回手写解析器（保住原文键序）',
    !usedFastPath(kFast) && ko(kFast) === ko(kSlow), ko(kFast) + '（应为 z,2,a）');

  // 7. 非法 JSON：退回手写解析器，拿到带行列的错误，且宽松模式仍可用
  const bad = '{ "a": 1, /* 注释 */ "b": [1,2,] "pad":"' + 'x'.repeat(300 * 1024) + '" }';
  let threw = null;
  try { parser.parse(bad); } catch (e) { threw = e; }
  check('非法 JSON 走手写解析器并给出 JsonParseError', !!threw && threw.name === 'JsonParseError',
    threw && String(threw.message).slice(0, 40) + '  (' + (bad.length / 1024).toFixed(0) + 'KB)');
  // 宽松样本：注释 + 裸键 + 尾随逗号，撑过 256KB
  const loose = '{ /* 注释 */ ' +
    Array.from({ length: 30000 }, (_, i) => 'k' + i + ': ' + i + ',').join(' ') +
    " s: '单引号', }";
  let len = null;
  try { len = parser.parse(loose, { lenient: true }); } catch (e) { len = null; }
  check('宽松模式仍可用（去注释/裸键/尾随逗号）',
    !!len && len.lenient === true && !!len.root && usedFastPath(len) === false,
    len && len.lenient ? 'lenient=true, ' + len.count + ' 节点' : '仍失败');

  // 8. 小文本不走快路径（阈值以下零行为变化）
  const small = makeBig(10);
  const sFast = parser.parse(small);
  const sSlow = parser.parse(small, { noFastPath: true });
  check('小文本两条路径一致', sameTree(sFast.root, sSlow.root) && sFast.count === sSlow.count);
  check('小文本走手写解析器', !usedFastPath(sFast));

  // 9. 全树物化后节点数正确（惰性视图不会漏节点）
  let cnt = 0, containers = 0;
  walkAll(fast.root, n => { cnt++; if (n.type === 'object' || n.type === 'array') containers++; });
  check('全树物化后节点数与统计一致', cnt === fast.count, cnt + ' vs ' + fast.count);
  check('全树物化后容器数合理', containers > 0 && containers < cnt);

  // 10. stats / setAllExpanded 在惰性树上的行为
  const st = parser.stats(fast.root);
  check('stats() 在惰性树上给出相同结果',
    st.count === slow.count && st.depth === slow.depth, st.count + '/' + st.depth);
  parser.setAllExpanded(fast.root, false);
  check('setAllExpanded(false) 只翻已物化容器且新节点也继承',
    fast.root.expanded === false && fast.root.__sess.deflt === false);
  const after = parser.parse(big);
  parser.setAllExpanded(after.root, false);
  check('setAllExpanded(false) 后新物化的子容器也是折叠态',
    after.root.entries[0].value.expanded === false);
  parser.setAllExpanded(after.root, true);
  check('setAllExpanded(true) 可恢复', after.root.entries[0].value.expanded === true);

  // 11. 性能
  const fx = path.join(__dirname, 'fixtures', 'big-20mb.json');
  if (fs.existsSync(fx)) {
    const t20 = fs.readFileSync(fx, 'utf8');
    parser.parse(t20);                                    // 预热
    const t0 = Date.now();
    const p20 = parser.parse(t20);
    const fastMs = Date.now() - t0;
    check('22MB 走快路径', usedFastPath(p20), p20.count.toLocaleString() + ' 节点');
    check('22MB 解析（含守卫）< 250ms', fastMs < 250, fastMs + 'ms');
    const t1 = Date.now();
    const slow20 = parser.parse(t20, { noFastPath: true });
    const slowMs = Date.now() - t1;
    check('手写解析器对照', slow20.count === p20.count,
      slowMs + 'ms（快路径快 ' + (slowMs / fastMs).toFixed(1) + ' 倍）');
    // 首帧只物化几千个节点：模拟查看器按文档序渲染 6000 行
    const t2 = Date.now();
    let rows = 0;
    const stack = [p20.root];
    while (stack.length && rows < 6000) {
      const n = stack.pop();
      rows++;
      if (n.type === 'object') {
        const es = n.entries;
        for (let i = es.length - 1; i >= 0; i--) stack.push(es[i].value);
      } else if (n.type === 'array') {
        const es = n.items;
        for (let i = es.length - 1; i >= 0; i--) stack.push(es[i]);
      }
    }
    check('渲染前 6000 行耗时 < 100ms', Date.now() - t2 < 100,
      (Date.now() - t2) + 'ms, 物化 ' + rows + ' 行');
  } else {
    console.log('  [SKIP] 未找到 tools/fixtures/big-20mb.json（性能用例跳过）');
  }

  console.log('\n' + pass + ' 通过, ' + fail + ' 失败');
  process.exit(fail ? 1 : 0);
}

run();
