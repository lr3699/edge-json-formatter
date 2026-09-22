# 大 JSON 高性能方案（调研 + 落地设计）

> 目标：**回到 1.1.7 的功能基线**（大文档仍能一次看到底、折叠/搜索/复制路径全都在），
> 把「大 JSON 格式化」做成**真·高性能**——不设 6000 行上限、不靠「滚到才渲染」的补丁。
>
> 本文所有数字都是在**本仓库**上实测的（`tools/bench-parse.js`、`tools/bench-mem.js`），
> 不是引用别人的宣传值。

---

## 一、结论先行

1. **解析早就不是瓶颈，别再优化解析。**
   22.2MB 文档：`parse()` 97ms，堆只净增 **8.2MB**。惰性树已经把「不建整棵树」做对了。
2. **唯一的瓶颈是渲染：一个节点一行真实 DOM。** 360,166 行的文档要 36 万行 DOM，浏览器必然崩。
   之前的 `TOTAL_ROWS = 6000` 上限、以及「超过 600KB 就切 CodeMirror」，本质都是在绕这个问题。
3. **业界唯一可行解是「树视图虚拟化」**，而且成熟实现（Dadroit / JSON Hero / svelte-jsoneditor）
   用的都是同一套：**放弃「嵌套 DOM 树」，改成「可见行流水线」**——
   把要显示的节点摊平成一个**行数组**，只渲染视口内的几十行。
4. **本项目已经有 80% 的地基**：惰性树（按需物化的节点包装）就是虚拟化需要的数据层。
   缺的只是把渲染层从「append 真实 DOM」换成「摊平 + 窗口渲染」。

---

## 二、现状实测（22.2MB / 360,166 行 / 614,571 节点）

| 阶段 | 耗时 | 堆净增 | 结论 |
| --- | --- | --- | --- |
| 读入文本 | — | 48.3 MB | 文本本身（JS 字符串） |
| `parse()`（原生 + 惰性树） | **97.4 ms** | **+8.2 MB** | ✅ 已经达标 |
| 全展开摊平成行数组（321,692 行） | 315.3 ms | **+161.4 MB** | ⚠️ 每行 JS 对象 ≈ 500 B，必须换成 TypedArray |
| 渲染 | — | — | ❌ 当前是 36 万行 DOM，不可行 |

第二条是关键：**就算是「摊平」这一步，用 JS 对象数组也会吃掉 161MB**。
换成 `Int32Array`（节点下标）+ `Uint8Array`（深度）后，同样的 321,692 行只要约 **1.6MB**，
差 **100 倍**——这是文档里所有「可见行流水线」实现都没写明、但决定成败的一步。

> 参考量级：一行真实 DOM（元素 + 样式 + 布局盒）约 1.5–3 KB。
> 36 万行 ≈ 500MB+ 的渲染开销，且布局/重排复杂度是超线性的。

---

## 三、全网方案横向对比

| 工具 | 解析方式 | 渲染方式 | 实测上限 | 关键取舍 |
| --- | --- | --- | --- | --- |
| **Dadroit JSON Viewer**（原生 C++） | SIMD 扫描，**不建对象树**，只建「存字节偏移的 parse cursor」 | 自绘 OpenGL 树控件 | **500MB**（100MB 用 1.2s / 内存 12MB，展开 15–40ms） | 桌面独占、收费 |
| **JSON Hero**（Web） | 流式 tokenizer → 轻量 AST | `react-virtual` 虚拟化树 | ~100MB（免费档 50MB） | 内存约为文件的 45% |
| **JSON Editor Online**（Web） | `svelte-jsoneditor` + `lossless-json` | 自研虚拟化 tree/text | 号称 512MB | —— |
| **jsoncrack.com**（Web） | 全量解析 + 节点图 | Canvas + React Flow | ~5MB 好用，50MB 只剩 2–4fps | 图形化复杂度是可见节点的平方级 |
| **Chrome DevTools** | `JSON.parse`，**无虚拟化** | 原生 DOM 树 | ~10MB | 就是「一节点一 DOM」的反面教材 |
| **Monaco / VS Code** | 逐行 token，只渲染视口行 | 行虚拟化 | 大文件会主动降级功能 | 定高行是前提 |

**共识（三份独立资料都指向同一点）**：

- 必须**放弃「嵌套 DOM 树」的心智模型**，改成 **visible-row pipeline**：
  *"Index the data, flatten only expanded branches, virtualize the resulting rows."*
  *"Collapsed branches disappear from the visible array immediately. Expanded branches insert their descendants in tree order."*
- **虚拟化只解决渲染，不解决解析 / 索引 / 深拷贝。** 本项目解析已达标，正好吃这个红利。
- **定高行优先**：行高固定，滚动数学是 O(1)，展开/折叠手感稳定。
  只有「长字符串要原地折行」时才需要动态测量，而那会带来滚动锚点漂移等一堆边界问题。
- 稳定标识（节点 id / 标准 JSONPath）要贯穿虚拟化、选中、复制、展开四件事，
  **不能把状态挂在「已挂载的行组件」上**，否则滚动时选中就丢。
- **别拿 `content-visibility: auto` 冒充虚拟化**：它只省绘制，节点仍然真实存在于 DOM 里。

### 一个反直觉但很重要的结论：**不要盲目上 Web Worker**

多份资料都提到「大 JSON 解析丢进 Worker」，但同一条链路里还有一个更贵的东西：
**结构化克隆（structured clone）**。Worker 把解析好的对象树 `postMessage` 回主线程时会
**深拷贝整个对象图**——内存翻倍，序列化/反序列化开销可能超过解析本身，
净效果是「把主线程的卡顿换成了更长的等待 + 双倍内存」。真正零拷贝的只有
**Transferable（ArrayBuffer 及其视图）**，且转移后原线程直接失效。

所以：

- **本项目现在不需要 Worker**：22MB 解析只要 97ms，且已经用「惰性树」避免了建整棵树。
  为了 97ms 去付结构化克隆的代价是负优化。
- **将来要冲 100MB+ 时**，正确形态是 Dadroit 那条路：
  Worker 里**只建索引**（字节偏移 / 深度 / 类型），用 `Int32Array` 等 TypedArray
  **零拷贝转移**回主线程；主线程按偏移按需取那一小段子树来渲染。
  ——注意「不能把 JSON 随便切块各自 `JSON.parse`」，任意字节边界不是合法 JSON。

---

## 四、落地设计（针对本仓库）

### 4.1 保留什么
- `src/content/json-parser.js` 的**惰性树**：这是虚拟化的数据层，不动。
  （`raw` 用原型 getter 按需生成、`entries`/`items` 按需物化——正是我们要的。）
- 全部观感与交互：折叠三角、类型配色、缩进引导线、点击复制路径、行号、压缩视图、搜索。
- `bigview.js`（CodeMirror）保留作为「纯文本视角」，但不再是唯一出路。

### 4.2 改什么：把 `viewer.js` 的渲染层换成虚拟窗口

```
现在：  节点 ──pushNode()──► 真实 DOM 行（每节点一行，分帧 append）
        └ 于是必须有 TOTAL_ROWS 上限 / 哨兵 / 切换到 CodeMirror

改成：  节点 ──摊平──► rows（TypedArray：节点下标 + 深度）
                      │
                      └─► 虚拟窗口：只把 [first..last] 这 ~50 行渲染成 DOM
                                     滚动 = 改窗口，DOM 数量恒定
```

**行模型（关键：用 TypedArray，不用对象数组）**

| 数组 | 类型 | 作用 |
| --- | --- | --- |
| `rowNode` | `Int32Array` | 每行对应的节点 id（稳定标识，用于选中/复制） |
| `rowDepth` | `Uint8Array` | 每行的缩进层级 |

321,692 行 ≈ **1.6MB**，而不是对象数组的 161MB。

**增量维护，不做全量重建**

- 展开一个容器：把它子树的可见行**按文档序插入**到该行之后；
- 折叠一个容器：把它子树的可见行**整段移除**；
- 代价与该子树规模成正比，**与整篇文档规模无关**。

于是「滚到第 20 万行」不再需要先把前 20 万行建出来——窗口直接按下标取。

**行高策略（需要你拍板的那一个决定）**

- **方案 A（推荐，业界默认）**：定高行 + 长值截断，点击/悬停看完整值。
  滚动数学 O(1)，永远丝滑；这也是 DevTools、Monaco、svelte-jsoneditor 的做法。
  代价：超长字符串默认显示省略号（现有 `white-space:pre-wrap` 要改成不换行）。
- **方案 B**：保留原地折行（`pre-wrap`），需要动态测高 + 高度缓存 + 滚动锚点补偿。
  观感与现在完全一致，但要多写一套测量/补偿逻辑，且快速滚动时容易跳动。

### 4.3 首次打开的展开策略
现在默认按 `expandDepth`（默认 2）展开。对 30 万行的文档，depth-2 全展开仍然很大，
所以初始展开要**按容器规模设阈值**：子元素超过 N（比如 200）的容器默认折叠，
并显示 `[128457]` 这样的规模提示（DevTools / JSON Hero 都这么做），用户点开才物化。

### 4.4 时间预算（按实测外推）

| 动作 | 目标 |
| --- | --- |
| 22MB 打开到首屏可交互 | < 300ms（解析 97ms + 首次摊平窗口 + 一次渲染） |
| 滚动 | 恒定 ~50 行 DOM，60fps |
| 展开 / 折叠任意容器 | 与子树规模成正比，单次 < 16ms 为佳，大容器分片 |
| 内存 | 文本 + 惰性树 8MB + 行表 1.6MB，合计约 60MB | 
| 上限 | 不再设行数上限；安全边界由内存决定（目标 100MB 内可用） |

### 4.5 无障碍（调研里被反复强调，别当收尾工作）
`role="tree"` / `role="treeitem"`、`aria-expanded` 只加在容器上、
显式 `aria-level` / `aria-posinset` / `aria-setsize`（DOM 已不再反映完整层级）、
方向键 + Home/End + type-ahead、焦点用 roving focus 或 `aria-activedescendant` 保持稳定。

---

## 五、分阶段实施

| 阶段 | 内容 | 可验证产出 |
| --- | --- | --- |
| **P0 地基** | 抽出「行模型」模块：`rowNode`/`rowDepth` TypedArray + 展开/折叠的增量插入与整段移除；纯逻辑、不碰 DOM | 单测：22MB 全展开 321,692 行、耗时与内存达标（node 侧可测） |
| **P1 虚拟窗口** | `viewer.js` 改为窗口渲染：spacer 撑总高 + `translateY` 定位窗口；滚动只改窗口 | 22MB 打开首屏 < 300ms；DOM 行数恒定 ≈ 50；滚动不掉帧 |
| **P2 交互对齐** | 折叠/展开、行号、点击复制路径、压缩视图、搜索定位到行、导出全部接到行模型上 | 1.1.7 的全部功能逐项回归通过 |
| **P3 展开阈值** | 大容器默认折叠 + 规模提示；`expandDepth` 带规模上限 | 打开 30 万行文档不出现长任务 |
| **P4 上限提升** | 冲 64MB / 100MB：视需要把「建索引」挪进 Worker，用 TypedArray 零拷贝回传 | 100MB 文档可打开、可滚动 |

**P0 可以先做且立即有价值**：它是纯数据层，能在 node 里用 `bench-mem.js` 直接量化，
失败了也不会污染 UI。

---

## 六、参考来源

- Tree View Virtualization for Massive JSON — offlinetools.org
  （扁平行模型 / 定高优先 / 虚拟化不解决解析 / 别用 content-visibility 冒充）
- Formatting Large JSON Files: Pagination and Performance — offlinetools.org
  （不能按任意字节切块解析；Worker + 索引 + 视口分页的架构）
- Processing 500MB JSON Without Crashing — aijsons.com
  （Dadroit 的 parse cursor/偏移模型；JSON Hero 的流式 tokenizer + react-virtual）
- Introducing JSON Hero — apihero.run（流式 tokenizer、react-virtual、ARIA 树）
- Web Workers vs Main Thread / Worker 大批量数据传输 — frontendinterviews.dev、segmentfault
  （结构化克隆的内存翻倍与开销；Transferable 才是零拷贝）
- JSON Editor Online 官网（512MB 上限；svelte-jsoneditor 技术栈）
