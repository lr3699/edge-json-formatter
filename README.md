# JSON 格式化查看器 · JSON Formatter Pro

一个 Microsoft Edge / Chrome 扩展（Manifest V3）：自动识别网页返回的 JSON，替换成带语法高亮、可折叠树、搜索定位的查看器。

界面风格参考了常见的在线 JSON 格式化工具：**键名加粗深色、字符串玫红、数字蓝色、布尔紫色、可折叠节点、保留转义开关**。

---

## 功能

| 分类 | 能力 |
| --- | --- |
| 自动接管 | `application/json`、`*/json`、`application/*+json` 响应自动格式化；`text/plain` 的 JSON 可选自动格式化 |
| 语法高亮 | 键名加粗、字符串 / 数字 / 布尔 / null 分色；支持浅色 + 深色两套主题（可跟随系统） |
| 可折叠树 | 逐节点折叠展开、一键折叠/展开全部、按层级展开（1~8 层）、折叠摘要（`… 13 个字段`） |
| 搜索定位 | 实时搜索键与值（含已转义内容），命中计数 `3/11`、上下跳转、自动展开命中路径、高亮标记 |
| 路径复制 | 点击键名复制 JSONPath（如 `$.data.list[0].orderId`），点击值复制值 |
| 保留转义 | 勾选时 `"a\nb"`、`"\u4e2d"` 原样显示源码转义；取消则还原为真实字符 |
| 输出控制 | 美化 / 压缩两种输出，缩进 2 / 4 空格 / Tab，一键复制、下载 `.json` |
| 精度保真 | 自研解析器保留源码原始切片，`600653836507516928` 这类大整数不会被 `Number` 精度截断 |
| 错误诊断 | JSON 非法时给出**行号 + 列号 + 出错行的插入符定位**，并提供「宽松解析」重试（去注释、单引号、尾随逗号、裸键） |
| 粘贴格式化 | **自己复制来的 JSON 也能格式化**：独立编辑页，粘贴 / 拖入 `.json` 或 `.txt` 即实时出结果，带逐行动效，`F` 可切全屏沉浸 |
| 入口 | 工具栏弹窗（含「粘贴 JSON 格式化」）、右键菜单（页面 / 选中内容 / 打开编辑页）、快捷键 `Alt+Shift+J`、设置页 |
| 安全隔离 | `.jf-root` 使用 `all: initial` 阻断宿主页面样式继承，配色与度量由查看器自带注入的 `<style>` 定义；随时可「还原原文」 |

## 目录结构

```
edge-json-formatter/
├── manifest.json                 # MV3 清单
├── src/
│   ├── shared/defaults.js        # 默认配置 + 存储读写（各环境共用）
│   ├── content/
│   │   ├── json-parser.js        # 带原始切片与行列定位的 JSON 解析器
│   │   ├── viewer.js             # 查看器 UI（不含 chrome.* API，可独立复用）
│   │   └── content.js            # 内容脚本：探测 + 注入 + 消息通道
│   ├── background/service-worker.js  # 右键菜单、快捷键、安装初始化
│   ├── popup/                    # 工具栏弹窗
│   ├── editor/                   # 「粘贴 JSON 格式化」独立编辑页
│   └── options/                  # 设置页
├── icons/                        # 16/32/48/128 图标 + 商店 300×300 图标
├── preview/demo.html             # 本地效果预览页（无需装扩展）
├── site/                         # 官网页（功能介绍 + 隐私政策），已上线
├── tools/
│   ├── build.js / build.ps1      # 打包：产出商店 zip 与可加载目录
│   ├── zip.js                    # 最小 ZIP 打包器（保证正斜杠 + UTF-8 名称）
│   ├── verify-package.js         # 上传前体检
│   ├── make_icons.py             # 纯标准库生成图标
│   ├── test-parser.js            # 解析器测试（19 项）
│   ├── test-server.js            # 端到端测试用的假 JSON 接口
│   ├── png_read.py               # 纯标准库 PNG 解码（取色分析用）
│   ├── analyze_ref.py            # 从设计稿中提取配色与排版参数
│   └── publish-pages.sh          # 发布 site/ 到 GitHub Pages
└── docs/                         # 上架资料、截图
```

## 本地安装（开发者模式）

**要加载的目录是 `dist/unpacked/`**（根目录就有 `manifest.json`，是这个扩展的最终形态）。
不要直接加载仓库根目录 —— 根目录会多出 `preview/`、`site/`、`tools/`、`docs/` 等无关内容。

1. 打开 `edge://extensions/`（Chrome 用 `chrome://extensions/`）。
2. 打开左下角 **开发人员模式**。
3. 点击 **加载解压缩的扩展**，选择：

   ```
   <仓库路径>/edge-json-formatter/dist/unpacked
   ```

4. 定位栏右边会出现扩展图标。访问任意返回 JSON 的接口即可看到效果。

> 想让它对本地 `file://` 的 JSON 也生效，需要在扩展详情页额外打开
> **「允许访问文件网址」**（Detail → Allow access to file URLs）。

### 四种看效果的方式

| 方式 | 命令 / 操作 | 说明 |
| --- | --- | --- |
| 试「粘贴格式化」 | `node tools/serve.js 18544` → <http://127.0.0.1:18544/src/editor/editor.html> | **无需安装扩展**。粘贴即格式化，布局与动效和扩展里完全一致（脱离扩展时顶栏「设置」按钮会自动隐藏） |
| 只看查看器 | 直接用浏览器打开 `preview/demo.html` | **无需安装扩展**，纯静态预览，适合调样式 |
| 看真实接管效果 | `node tools/test-server.js 18543` 后访问 <http://127.0.0.1:18543/api/order> | 内容脚本真实运行，推荐用这个验收 |
| 看真实接口 | 随便打开一个 JSON 接口，如 <https://jsonplaceholder.typicode.com/todos/1> | 需要网络 |

> 编辑页也可以直接双击 `src/editor/editor.html` 用浏览器打开（`file://`）。
> 但走本地服务更好：`file://` 下 `localStorage`（用来记住分隔条位置）可能被浏览器限制。
> `node tools/serve.js` 启动后首页 <http://127.0.0.1:18544/> 有全部预览入口的索引。

### 改完代码怎么生效

内容脚本不会热更新。改完 `src/` 里的文件后：

1. 回到 `edge://extensions/`，点该扩展卡片上的 **🔄 重新加载**；
2. **刷新**目标页面（内容脚本只在页面加载时注入）。

少了第 2 步最常见的症状是「改了没反应」。

### 常用入口

| 入口 | 怎么用 |
| --- | --- |
| 自动接管 | 打开 JSON 页面即可 |
| 工具栏弹窗 | 点扩展图标 → 手动格式化当前页面 |
| 右键菜单 | 页面空白处右键 → 格式化当前页面 / 格式化选中的内容 |
| 快捷键 | `Alt+Shift+J` 切换格式化 / 还原原文 |
| 设置页 | 扩展详情页 → 扩展选项；或弹窗里的设置入口 |

### 粘贴 JSON 格式化（编辑页）

除「接管网页上的 JSON」之外，扩展还有一个独立的编辑页，用来格式化**自己手里**的 JSON：
从聊天记录、服务端日志、终端里复制出来的一段内容，没地方贴的时候用它。

怎么打开（三个入口，指向同一个页面）：

| 入口 | 位置 |
| --- | --- |
| 工具栏弹窗 | 顶部主按钮「粘贴 JSON 格式化」 |
| 右键菜单 | 任意页面右键 → 「粘贴 JSON 格式化（打开编辑页）」 |
| 设置页 | 「快速上手」卡片里的按钮 |

同一时间只会有一个编辑页标签，重复点会聚焦已经打开的那个（不再连开一排）。

页面用法：

- **左栏**：`Ctrl+V` 粘贴；或把 `.json` / `.txt` 拖进来；或点「示例」灌一段样例。输入 220ms 防抖后自动格式化。
- **右栏**：和接管网页时完全同一个查看器 —— 折叠树、语法高亮、搜索、路径复制、导出。
- **中间分隔条**：可拖动调整左右宽度（双击恢复默认，键盘 `←/→` 微调），位置记在 `localStorage`。
- `Ctrl+Enter` 强制格式化（内容超过「自动格式化上限」时用它）。
- `F` 切换**全屏沉浸模式**（`Esc` 退出）：隐藏输入区与分隔条，格式化结果独占整个工作区，
  同时请求浏览器全屏。即使全屏被拒（例如页面嵌在 iframe 里没给 `allowfullscreen`），
  沉浸布局也照常生效。
- 内容变更后会播放逐行错落浮现的入场动效；逐字打字不播，避免一直闪。
  系统开了「减弱动态效果」（`prefers-reduced-motion`）时自动关闭动效。

```
┌─ 顶栏：品牌 · Ctrl+Enter / F 提示 · 全屏 · 设置 ─────────────────┐
├──────────────────────┬─┬──────────────────────────────────────┤
│ 输入                  │⇔│ 输出（可折叠 / 高亮 / 搜索的树）        │
│ textarea + 统计        │ │ 工具栏 · 正文 · 状态栏                  │
└──────────────────────┴─┴──────────────────────────────────────┘
按 F 后 ─────────────────────────────────────────────────────────
┌─ 顶栏：品牌 · 退出全屏 · 设置 ──────────────────────────────────┐
├────────────────────────────────────────────────────────────────┤
│ 输出独占整个工作区（输入区与分隔条隐藏）                          │
└────────────────────────────────────────────────────────────────┘
```

### 商店版审核通过后

审核通过（最长 7 个工作日）后，建议**先卸载开发者模式版本，再从商店安装**：
两者 ID 相同，同时存在会互相覆盖，容易分不清当前跑的是哪一份。

## 视觉规格

配色取自设计稿的像素级取色（`tools/analyze_ref.py`）：

| 元素 | 浅色 | 深色 |
| --- | --- | --- |
| 键名 | `#92278F` 紫 | `#C98AD4` |
| 字符串 | `#3AB54A` 绿 | `#79D17F` |
| 数字 | `#20A8E0` 浅蓝 | `#4DC4F0` |
| 布尔 | `#E85050` 珊瑚红 | `#FF8A8A` |
| 折叠标记 | `#E85050` 圆角方框 ⊕/⊖ | 同左 |
| 背景 | `#FFFFFF` | `#15171C` |

排版要点：折叠标记位于**键与括号之间**（`"data": ⊟ {`）；层级用嵌套容器 + 左侧引导线表达；
行高 1.75，每层缩进 16px。

## 本地测试

```bash
# 解析器单元测试（19 项）
node tools/test-parser.js

# 启动假接口，手工验证
node tools/test-server.js 18543
#   http://127.0.0.1:18543/api/order    合法 JSON，应被接管
#   http://127.0.0.1:18543/api/plain    text/plain 的 JSON
#   http://127.0.0.1:18543/api/broken   非法 JSON，应显示错误卡片
#   http://127.0.0.1:18543/api/large    约 2.5 万行，性能验证
#   http://127.0.0.1:18543/api/html     普通网页，不应被接管

# 打开 preview/demo.html 可直接预览界面（无需安装扩展）
```

编辑页的端到端验收（会自己起 Edge、加载 `dist/unpacked`、模拟粘贴并抓动效关键帧）：

```bash
# 1) 先拉起一个带扩展的临时 Edge（必须用反斜杠路径，并加 --enable-unsafe-extension-debugging）
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --remote-debugging-port=9334 --remote-allow-origins='*' \
  --user-data-dir="C:\Users\<你>\AppData\Local\Temp\jf-verify-profile" \
  --load-extension="C:\...\edge-json-formatter\dist\unpacked" \
  --disable-extensions-except="C:\...\edge-json-formatter\dist\unpacked" \
  --enable-unsafe-extension-debugging --no-first-run about:blank

# 2) 再跑验收脚本
python tools/verify-editor.py --port 9334 --outdir docs
```

它会检查：逐行入场动效确实在跑（页面内采样 `.jf-row` 的 `animation-name` / `animation-delay`，
不靠外面 sleep 后单次读数——CDP 往返延迟很容易错过动画窗口而误判）、
**全屏沉浸能不能正确进入与退出**（`html.is-fullscreen` / `.workspace.is-focus` 成对出现与收起、
输入面板随之隐藏/恢复、按钮文案与图标切换）、
**闪动回归**（连续输入时输出面板不该被加上 `is-busy` / `is-flash`，状态胶囊圆点的
`animationName` 必须是 `none`，扫描条伪元素不该存在）、
字号与字体、分隔条宽度、错误态文案、弹窗与设置页能渲染、
设置页按钮能拉起编辑页且不会重复开标签，并把各状态截图写到 `docs/`。
任一项不符会打印清单并以非零码退出。

只想验证**脱离扩展的静态预览页**（改样式时最常用，不用每次加载扩展）：

```bash
node tools/serve.js 18544 &
# 起任意带 --remote-debugging-port 的 Edge/Chrome 后：
python tools/verify-editor.py --port 9335 --outdir docs \
  --static-url "http://127.0.0.1:18544/src/editor/editor.html"
```

`--static-url` 模式会跳过扩展 ID 探测和 popup / options 检查。

## 打包

```bash
node tools/build.js                 # 或：powershell -ExecutionPolicy Bypass -File tools/build.ps1
node tools/verify-package.js        # 上传前体检
```

产物：

- `dist/json-formatter-pro-1.1.0.zip` —— 商店上传用，条目名统一使用正斜杠，符合 ZIP 规范
- `dist/unpacked/` —— 可直接被浏览器「加载解压缩的扩展」

`verify-package.js` 会检查 ZIP 分隔符、manifest 必填项与字段长度限制、图标/脚本引用是否齐全、
有无多余文件混入，并列印权限清单便于撰写商店说明。

## 上架

见 [`docs/SUBMISSION.md`](docs/SUBMISSION.md)（Edge 加载项商店完整流程）与
[`docs/store-listing.md`](docs/store-listing.md)（可直接粘贴的商店文案）。

## 权限说明

| 权限 | 用途 |
| --- | --- |
| `storage` | 保存用户的显示偏好 |
| `contextMenus` | 提供「格式化当前页面 / 选中内容」右键入口 |
| `activeTab` | 弹窗与当前标签页通信 |
| `host_permissions: <all_urls>` | 内容脚本需要在 JSON 页面上运行才能接管渲染 |
| `commands`（非权限） | 注册 `Alt+Shift+J` 快捷键 |

不采集、不上传任何数据；无网络请求；无远端代码。详见 [`PRIVACY.md`](PRIVACY.md)。
