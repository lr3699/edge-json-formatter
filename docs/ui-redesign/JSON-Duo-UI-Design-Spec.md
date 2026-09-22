# JSON Duo · 界面重设计方案（v1.0）

> 设计对象：JSON Duo 编辑器（浏览器扩展 `editor.html` + 网页版 `site/app.html`）
> 风格方向：**现代清爽 · 浅色为主 · 留白充足**
> 交付物：本规范 + `prototype/index.html`（可交互高保真原型）+ `tokens.css`（可直接落地的令牌表）
> 设计日期：2026-09-22

---

## 0. 设计目标与原则

| 编号 | 原则 | 具体表现 |
| --- | --- | --- |
| P1 | **内容优先** | 所有 chrome（顶栏、工具条、状态带）一律降饱和、去边框，把视觉重量让给 JSON 正文 |
| P2 | **留白即层级** | 用间距分隔层级，而不是靠描边；相邻区块间距 ≥12px，面板内边距 ≥14px |
| P3 | **密度可调** | 默认「舒适」密度（行高 24px），设置里提供「紧凑（20px）/ 舒适（24px）/ 宽松（28px）」 |
| P4 | **状态可见** | 解析成功/失败/大文档降级三种状态在右栏底栏一眼可辨，不依赖颜色单一通道（颜色 + 图标 + 文案） |
| P5 | **不牺牲性能** | 视觉升级不得触碰虚拟化渲染契约（见 §7 红线） |
| P6 | **WCAG AA** | 正文对比度 ≥4.5:1，大字/图标 ≥3:1，焦点可见，最小点击区 32×32 |

### 与旧版的关键差异

1. 背景从「gray-100 平铺」改为**画布 + 悬浮卡片**：`#F6F7F9` 画布，`#FFFFFF` 面板配柔和双层阴影，层级靠阴影而非 1px 描边表达。
2. 去掉背景 aurora 光斑动画 —— 与「清爽」冲突且常驻消耗合成层，改为极淡的静态渐变。
3. 顶栏从 3 个带文字图标按钮收敛为**图标按钮 + 悬浮 tooltip**，把宽度还给工作区。
4. 面板头工具条从「5 个带文字按钮」收敛为**主操作 2 个（示例 / 清空）+ 溢出菜单**，减少视觉噪音。
5. 圆角统一上调到 12/16px，按钮 8px，输入控件 10px —— 更「现代」。

---

## 1. 布局框架

```
┌──────────────────────────────────────────────────────────────┐
│ Topbar  56px   brand │ 快捷键提示 │ [输入栏] [全屏] [设置]    │
├──────────────────────────────────────────────────────────────┤
│  Workspace  padding 16px · gap 14px                          │
│  ┌──────────────────────┐ ┆ ┌─────────────────────────────┐  │
│  │ Panel 输入            │ ┆ │ Panel 结果                   │  │
│  │  head 44px           │ ┆ │  head 44px（工具条）          │  │
│  │  编辑器区 1fr        │ ┆ │  树视图 / 大文档视图 1fr      │  │
│  │  foot 34px（字符数） │ ┆ │  foot 34px（状态+路径+节点） │  │
│  └──────────────────────┘ ┆ └─────────────────────────────┘  │
│                        Splitter 8px                           │
└──────────────────────────────────────────────────────────────┘
```

### 尺寸规范（px）

| 元素 | 值 | 说明 |
| --- | --- | --- |
| 顶栏高度 | 56 | 内容垂直居中，左右内边距 20 |
| 工作区内边距 | 16（<1280 时 12） | 四周等宽 |
| 面板间距 / 分隔条 | 14 / 8（命中区） | 分隔条可见线 2px，grip 24×4 圆角 |
| 面板头 / 底 | 44 / **34** | **底栏 34px 为硬约束**，左右两栏必须等高 |
| 面板圆角 | 16 | `--r-lg` |
| 默认分栏比 | 34% / 66% | `--split: 34%`；可拖，双击复位 |
| 最小面板宽 | 输入 320 / 结果 420 | 低于则不再收缩 |
| 设置抽屉宽 | 360 | ≥1280 时右侧推出式，<1280 时覆盖式 + 遮罩 |

### 响应式断点

| 断点 | 布局 |
| --- | --- |
| ≥1440 | 双栏 34/66，顶栏显示快捷键提示 |
| 1024–1439 | 双栏 40/60，隐藏快捷键提示，工具条收进溢出菜单 |
| 768–1023 | **上下堆叠 + 顶部 Tab（输入 / 结果）**，分隔条改为可拖高度 |
| <768 | 单栏 Tab 切换，抽屉全屏 |

### 全屏 / 沉浸态（沿用现有三态语义，只换视觉）

- `.is-solo`：左栏以 200ms 位移+淡出收起，右栏宽度过渡；显隐**只由该 class 决定**，逻辑不变。
- `.is-focus`：画布内边距收到 8px，顶栏半透明悬浮；三列不被窄屏媒体查询接管。
- `.is-bigdoc`：顶栏与底栏各减 4px 高度，工具条图标化。

---

## 2. 设计令牌（Design Tokens）

完整可用版本见同目录 `tokens.css`。核心表如下。

### 2.1 中性色（浅色主题 · 默认）

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--bg-canvas` | `#F6F7F9` | 应用画布 |
| `--bg-surface` | `#FFFFFF` | 面板、抽屉 |
| `--bg-surface-2` | `#FAFBFC` | 面板头/底、分组背景 |
| `--bg-surface-3` | `#F2F4F7` | 输入框、hover、chip |
| `--bg-inset` | `#FCFCFD` | 代码/编辑器内底 |
| `--border-subtle` | `#EDEFF3` | 行分隔、极弱边界 |
| `--border` | `#DDE1E7` | 常规描边 |
| `--border-strong` | `#C6CCD6` | 分隔条、激活描边 |
| `--text-1` | `#14181D` | 主文本（对比 15.8:1） |
| `--text-2` | `#4A5361` | 次要文本（7.4:1） |
| `--text-3` | `#7C8695` | 辅助/占位（4.6:1） |
| `--text-4` | `#A6AEBB` | 禁用（3.1:1，仅用于非文本） |

### 2.2 品牌与语义色

| 令牌 | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- |
| `--brand-100` | `#E4F5EE` | `#12352A` | 品牌浅底 |
| `--brand-500` | `#1FA97F` | `#35BE8E` | 主按钮、品牌标记 |
| `--brand-600` | `#158A66` | `#4ACB9C` | hover / 激活 |
| `--accent-500` | `#3B6FF6` | `#6E9BFF` | 链接、焦点环、选中 |
| `--success-500` | `#17A673` | `#3FCB8E` | 解析成功 |
| `--warning-500` | `#D98A1F` | `#F0B45C` | 宽松解析提示 |
| `--danger-500` | `#DC4A4A` | `#FF7B7B` | 解析失败、破坏性操作 |
| `--ring` | `rgba(59,111,246,.35)` | `rgba(110,155,255,.40)` | focus-visible |

### 2.3 JSON 语法色（白底全部 ≥4.5:1）

| 类型 | 浅色 | 深色 |
| --- | --- | --- |
| key | `#2F5FD0` | `#7AA2F7` |
| string | `#17794E` | `#6BC48B` |
| number | `#B4571B` | `#E5A85C` |
| boolean | `#7C4DD8` | `#B08CF5` |
| null | `#8790A0` | `#7C8798` |
| punctuation | `#A3ACBA` | `#6B7482` |

> 颜色**不是唯一通道**：键名同时用 500 字重区分，null/布尔另配图标。

### 2.4 字体

```
--font-ui:  "Inter", system-ui, -apple-system, "Segoe UI",
            "Microsoft YaHei UI", "PingFang SC", sans-serif;
--font-mono:"JetBrains Mono", "Cascadia Mono", Consolas,
            ui-monospace, SFMono-Regular, Menlo, monospace;
```

| 级别 | 字号 / 行高 | 用途 |
| --- | --- | --- |
| `--fs-micro` | 11 / 16 | 徽标、快捷键 chip |
| `--fs-xs` | 12 / 18 | 底栏、tooltip、路径 |
| `--fs-sm` | 13 / 20 | **UI 默认**（按钮、面板标题） |
| `--fs-md` | 14 / 22 | **代码与树行默认** |
| `--fs-lg` | 16 / 24 | 抽屉分组标题 |
| `--fs-xl` | 20 / 28 | 空状态标题 |
| `--fs-2xl` | 28 / 36 | 抽屉主标题 |

### 2.5 间距（4px 基准）

`2 / 4 / 6 / 8 / 12 / 14 / 16 / 20 / 24 / 32 / 40 / 48`

| 场景 | 值 |
| --- | --- |
| 面板内边距 | 14（<1280 时 12） |
| 面板头元素间距 | 8 |
| 按钮内边距（md） | 0 12 |
| 树行左右内边距 | 12 |
| 抽屉分组间距 | 24 |

### 2.6 圆角

`--r-xs 6` · `--r-sm 8` · `--r-md 10` · `--r-lg 12` · `--r-xl 16` · `--r-full 999`

面板 16、卡片 12、按钮 8、输入控件 10、chip full、抽屉左上/左下 16。

### 2.7 阴影（双层，浅色）

```
--e1: 0 1px 2px rgba(16,24,40,.05);
--e2: 0 2px 8px -2px rgba(16,24,40,.08), 0 1px 2px rgba(16,24,40,.04);
--e3: 0 12px 32px -12px rgba(16,24,40,.16), 0 2px 6px rgba(16,24,40,.05);
--e4: 0 24px 64px -20px rgba(16,24,40,.26), 0 4px 12px rgba(16,24,40,.06);
```

面板 `e2`、抽屉 `e4`、下拉/Toast `e3`、hover 由 e2→e3。深色模式阴影加深并叠加 1px 内描边。

### 2.8 动效

| 令牌 | 值 | 场景 |
| --- | --- | --- |
| `--d-instant` | 80ms | hover 底色 |
| `--d-fast` | 140ms | 按钮按下、chip |
| `--d-base` | 200ms | 面板收起、抽屉 |
| `--d-slow` | 320ms | 抽屉遮罩、Toast 进出 |
| `--e-std` | `cubic-bezier(.2,.8,.2,1)` | 通用 |
| `--e-out` | `cubic-bezier(.16,1,.3,1)` | 入场 |
| `--e-in` | `cubic-bezier(.4,0,1,1)` | 退场 |

**强制**：`@media (prefers-reduced-motion: reduce)` 下所有 transition/animation 置为 `0.01ms`。
**禁止**：给树行加入场动画（滚动时会每帧闪）—— 沿用现有 `jf-late` 抑制策略。

---

## 3. 组件库

### 3.1 按钮

| 变体 | 背景 | 文字 | 边框 | 用途 |
| --- | --- | --- | --- | --- |
| Primary | `brand-500` | `#fff` | 无 | 主操作（格式化、应用） |
| Secondary | `surface` | `text-1` | `border` | 次操作 |
| Ghost | 透明 | `text-2` | 无 | 工具条图标按钮，hover 出 `surface-3` |
| Subtle | `surface-3` | `text-1` | 无 | 高频切换 |
| Danger-ghost | 透明 | `danger-500` | 无 | 清空、重置 |

尺寸：`sm 28` · `md 32` · `lg 40`；图标按钮 `32×32`（图标 16px，stroke 1.75）。
状态：hover、active（`scale(.97)`）、focus-visible（2px ring + 2px offset）、disabled（`opacity .45` + `cursor:not-allowed`）、loading。

### 3.2 图标按钮 + Tooltip

顶栏与工具条一律 32×32 图标按钮，文字说明走 tooltip：
`delay 400ms` 出现，120ms 淡入，永远显示在按钮下方 6px，`aria-label` 与 tooltip 文案同源。

### 3.3 面板（Card）

```
.panel { background:var(--bg-surface); border-radius:var(--r-xl);
         box-shadow:var(--e2); display:flex; flex-direction:column; }
.panel-head { height:44px; padding:0 14px; border-bottom:1px solid var(--border-subtle);
              display:flex; align-items:center; justify-content:space-between; }
.panel-body { flex:1; min-height:0; overflow:hidden; }
.panel-foot { height:34px; padding:0 14px; display:flex; align-items:center; gap:12px;
              border-top:1px solid var(--border-subtle); background:var(--bg-surface-2); }
```

面板头左侧带 6px 状态圆点（`dot-in` 灰蓝 / `dot-out` 品牌绿）标识输入/输出。

### 3.4 分隔条（Splitter）

- 可见态：2px `--border-subtle` 竖线。
- hover/拖动：线变 2px `--brand-500`，中心浮出 24×4 `border-radius:999` 的 grip。
- 命中区 8px（`cursor:col-resize`），键盘：`Tab` 聚焦 + `←/→` 每次 2%，`Home` 复位。
- 双击复位 34%。

### 3.5 树行（Tree Row）

| 项 | 规范 |
| --- | --- |
| 行高 | **24px（= 14px × 1.7，硬约束）** |
| 缩进 | 每层 16px，由 `--jf-depth` 单变量驱动 |
| 参考线 | `repeating-linear-gradient` + `background-size` 裁剪（**不生成嵌套 DOM**） |
| 行号列 | 右侧钉列，`font-variant-numeric: tabular-nums`，`color: text-4`，`opacity .6`，hover 全显 |
| hover | 背景 `surface-3`，左侧 2px `brand-500` 指示条 |
| selected | 背景 `accent-100`，文字 `text-1`，500 字重 |
| 折叠箭头 | 14px chevron，`rotate(90deg)` 200ms；叶子节点占位但不显示 |
| 超长值 | 512 字符截断 + `…`，全文进 `title` 与点击复制 |
| 类型图标 | array `[]` / object `{}` / string `""` / number `#` / bool `◇` / null `∅`，12px，`text-3` |

### 3.6 底栏状态带（Status Foot）

左：`字符数 · 行数 · 文件名`。右：`状态 pill + 路径/节点信息 + 消息`。

| 状态 | 色 | 图标 | 文案 |
| --- | --- | --- | --- |
| 就绪 | `text-3` | ○ | 就绪 |
| 成功 | `success` | ✓ | 已格式化 · 24 节点 |
| 警告 | `warning` | △ | 宽松解析：已修 N 处尾随逗号 |
| 失败 | `danger` | ✕ | 第 12 行第 5 列：意外字符 |
| 大文档 | `info` | ⚡ | 大文档视图 · 36 万行 |

### 3.7 分段控件（Segmented）

结果视图切换「树 / 压缩 / 源码」：容器 `surface-3` + `r-md`，滑块 `surface` + `e1`，切换 200ms `--e-std`。高度 28，内边距 2。

### 3.8 搜索

面板头右侧常驻 200px 搜索框（聚焦展开到 280px）：`r-md`、`border`、左侧 14px 放大镜。
匹配项背景 `rgba(217,138,31,.16)`，当前项 `--warning-500` 底 + 白字；右侧显示 `3/17` 与上下箭头；`Enter` 下一处，`Shift+Enter` 上一处，`Esc` 关闭。

### 3.9 设置抽屉

- 右侧推出，宽 360，圆角仅左侧 16，阴影 `e4`，遮罩 `rgba(16,24,40,.28)` + 2px 背景模糊。
- 结构：标题行（关闭按钮居右）→ 分组（外观 / 格式化 / 大文档 / 快捷键）→ 底部操作条（恢复默认 / 完成）。
- 控件行高 40，左标签右控件，`border-subtle` 分隔（最后一行不画）。
- 控件：**开关**（40×22，滑块 18，品牌绿）、**下拉**（`r-sm`）、**滑块**（数字回显）、**步进器**（字号）。
- 动效：抽屉 `translateX(100%)→0` 320ms `--e-out`，遮罩淡入 200ms。焦点进入时聚焦首个控件，Esc 关闭，`focus-trap`。

### 3.10 空状态（Welcome）

- 120×96 线性插画（沿用现有 SVG 语义，改 1.5px 描边 + 品牌绿点缀）。
- 标题 20px `text-1`，说明 13px `text-2`，三点能力清单带品牌绿 ✓。
- 提供「载入示例」「粘贴剪贴板」「拖入文件」三个入口（后两个在网页版可用）。

### 3.11 Toast

右下角距边 20，`surface` + `e3` + `r-lg`，左侧 3px 语义色条，自动 3s 消失，最多堆叠 3 条。

### 3.12 快捷键 Chip

`<kbd>`：`surface-3` + 1px `border` 下缘阴影，`r-xs`，11px mono，高度 18，间距 2。

---

## 4. 交互流程

### 4.1 主流程（粘贴 → 格式化 → 查看）

```
粘贴/拖入/输入
   ├─ 解析成功 → 右栏渲染树，底栏"已格式化 · N 节点"，Toast 无
   ├─ 宽松解析成功 → 底栏 warning pill「已修 N 处」，可点击展开修复清单
   ├─ 解析失败 → 底栏 danger pill（行/列）+ 编辑器对应行高亮 + 右栏保留上次结果并置灰
   └─ 超过 600KB → 自动切大文档视图，顶栏出现⚡标记，Toast 提示「已切换大文档视图」
```

### 4.2 键盘

| 键 | 行为 |
| --- | --- |
| `Ctrl/⌘ + Enter` | 立即格式化 |
| `Ctrl/⌘ + K` | 聚焦搜索 |
| `Ctrl/⌘ + ,` | 打开设置 |
| `F` | 全屏 |
| `[` | 收起/展开输入栏 |
| `Esc` | 退出全屏 / 关闭抽屉 / 清空搜索（按层级） |
| `←/→` | 折叠/展开当前节点 |
| `Tab` | 在顶栏 → 输入区 → 工具条 → 结果区 → 底栏间循环，焦点始终可见 |

### 4.3 微交互清单

1. 粘贴瞬间：输入区底部一条 2px 品牌绿进度条（120ms 扫过）。
2. 树首次渲染：节点按深度 20ms 阶梯淡入（仅首屏，滚动补画不带动画）。
3. 复制成功：按钮图标 200ms 变 ✓，1.2s 后复原。
4. 分隔条拖拽时：两侧面板 `transition:none`，松手恢复，避免拖影。
5. 面板收起：宽度 200ms `--e-out` + 内容 120ms 淡出。

---

## 5. 无障碍（WCAG 2.1 AA）

- **对比度**：正文 ≥4.5:1，≥18px 或粗体 ≥3:1，非文本 UI 组件 ≥3:1。语法色表已逐项核算。
- **焦点**：统一 `:focus-visible { outline:2px solid var(--accent-500); outline-offset:2px; border-radius:inherit }`；抽屉 `focus-trap`，Esc 关闭并归还焦点。
- **语义**：`role="separator"` + `aria-orientation` + `aria-valuenow`（分隔条）；树用 `role="tree"`/`treeitem` + `aria-expanded` + `aria-level`；状态 pill `role="status" aria-live="polite"`，错误 `aria-live="assertive"`。
- **点击区**：所有可点元素 ≥32×32；树行 24px 高但整行宽可点（行内操作按钮独立 28×28 并带 `aria-label`）。
- **动效**：`prefers-reduced-motion` 全量降级。
- **缩放**：根字号用 rem，200% 缩放下面板改为堆叠且无横向滚动。
- **色觉**：状态绝不只靠颜色，全部配图标 + 文案。

---

## 6. 落地清单（给开发）

1. 新建 `src/theme/tokens.css`，把 §2 全部令牌写进去；`editor.css` 与 `viewer.js` 内的硬编码色值逐步替换为 `var()`。
2. `src/editor/editor.html` 与 **`site/app.html` 同步改**（后者是手工维护的，不同步会少节点）。
3. 工具条改为图标按钮 + tooltip，文案保留在 `title` / `aria-label`。
4. 面板头按钮从 5 个收敛为 2 主 + 溢出菜单（`⋯`）。
5. 新增 `密度` 设置项，作用于 `--row-h`（紧凑 20 / 舒适 24 / 宽松 28）。
6. 语法色抽到令牌，供树视图与大文档视图共用。
7. 给 DOM 赋值前**一律判空**（历史上曾因装饰节点缺失导致结果区全空白）。

---

## 7. 红线（不得改动）

来自已落地并验收的虚拟化方案，视觉改造**不能**触碰：

1. **三层 DOM 契约**：`.jf-body`（relative + overflow-y:auto）→ `.jf-sizer`（撑总高，滚动时不改高度）→ `.jf-window`（absolute + `translateY`）。滚动只改 translateY 与窗口内容。
2. **行高即坐标系**：`ROW_H = round(fontSize × 1.7)`。改字号/密度必须触发 `layout()` 重算 sizer，否则行号与滚动位置全部错位。
3. **事件委托**：整棵树只有一个 `click` 监听挂在 body 上，靠 `data-i` 反查行下标。逐行挂监听会在换行时 churn。
4. **首屏动画抑制**：后续补画的行加 `jf-late` 不播动画。
5. **输出全文**：压缩视图 `COMPACT_MAX` 只是屏幕策略，复制/下载走 `outputText()` 必须完整全文。
6. **底栏 34px**：左右两栏底栏必须等高，否则错行。
7. **定位走 hint**：跳行/搜索用 `revealRow(index)`，禁止 `indexOf` 全表扫描（32 万行 12ms）。
