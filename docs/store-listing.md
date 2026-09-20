# 商店一览文案（可直接复制到 Partner Center）

> **本次实际提交的是英文版**（见下方「已提交内容」一节）——因为 manifest 没有做
> `_locales` i18n，Partner Center 只识别出 `English (United States)` 一种语言，
> 文案按该语言写审核更顺。下面中文版留作以后用 `Add a language` 补中文（简体）时使用。

## 已提交内容（2026-09-20，English (United States)）

### Description

```
JSON Formatter Pro automatically turns raw JSON responses into a clean, collapsible, syntax-highlighted tree — no more squinting at one endless line of minified JSON.

FEATURES
• Automatic detection — open any JSON URL or API response and it is formatted instantly
• Syntax highlighting with both light and dark themes
• Collapsible tree — expand or collapse objects and arrays node by node
• Instant search — filter keys and values, and jump between matches
• Copy JSON path — one click copies a path such as data.items[0].id
• Escape control — keep or restore \uXXXX escapes exactly as you prefer
• Line numbers, compact mode, font size and indent width options
• 100% local — all parsing happens in your browser; nothing is uploaded

HOW TO USE
1. Open a JSON API endpoint or a .json file in Microsoft Edge.
2. The viewer takes over automatically. If it does not, click the toolbar icon and press Format.
3. Press Alt+Shift+J to toggle formatting on the current page.
4. Configure theme and indentation on the options page.

TYPICAL USES
Debugging REST and GraphQL APIs, inspecting configuration files, reading logs, and reviewing webhook payloads.

PRIVACY
This extension does not collect, store or transmit any personal data. Preferences such as theme, indent width and font size are saved locally in your own browser.
```

### Search terms（7 个，合计 15 词 ≤ 21 上限）

```
JSON
JSON formatter
JSON viewer
JSON pretty print
API response viewer
JSON highlighter
JSON tree
```

### 素材

- Extension logo：`icons/store-icon-300.png`（300×300）
- Screenshots（6 张，1280×800）：`docs/shots/` 下的
  `shot-light` / `shot-dark` / `shot-search` / `shot-lines` / `shot-compact` / `e2e-packaged`

### Notes for certification（1488 字符，已提交）

```
JSON Formatter Pro is a client-side JSON viewer. No account, credentials or special setup is required to test it.

HOW TO TEST
1. Install the extension and open a public JSON endpoint, for example https://jsonplaceholder.typicode.com/todos/1 — the response should render as a collapsible, syntax-highlighted tree instead of raw text.
2. Use the toolbar to collapse/expand all nodes, change the indent width, switch between the light and dark theme, and toggle line numbers.
3. Type a keyword into the search box to filter keys and values; click the path bar to copy a JSONPath-style path such as data.list[0].id.
4. Click the toolbar icon to open the popup, then open the options page (right-click the icon > Options) to change theme, indent width, font size and auto-collapse depth.
5. Press Alt+Shift+J, or use the right-click menu entry, to toggle between the formatted view and the original raw text.
6. Also try a non-JSON page: the extension must not alter it.

PERMISSIONS
- storage: saves display preferences locally in the browser only.
- contextMenus: adds the right-click entry used in step 5.
- activeTab: lets the toolbar popup communicate with the current tab.
- <all_urls> host permission: the content script must read the page text to decide whether the response is JSON before it takes over rendering.

PRIVACY AND REMOTE CODE
All parsing happens locally in the browser. The extension collects and transmits no user data. It bundles no analytics and loads no remote code.
```

### Privacy 页实际填写内容

- Single purpose：识别网页返回的 JSON 内容，并将其渲染为可折叠、带语法高亮的查看器，帮助开发者阅读与调试接口返回数据。
- `storage`：保存用户的显示偏好（主题、缩进宽度、字号、是否自动折叠等本地设置），仅写入浏览器本地存储，不上传任何服务器。
- `contextMenus`：在页面右键菜单中提供「格式化 / 折叠 JSON」入口，方便用户对当前页面或选中内容快速调用扩展的格式化功能。
- `activeTab`：用户点击工具栏图标时，让弹窗能够读取并与当前活动标签页通信，从而格式化该页面的 JSON 内容。
- Host permission：扩展需要在页面加载时读取页面文本，以判断该页面是否为 JSON 响应，从而决定是否接管渲染。所有解析均在本地完成，不收集、不发送任何数据。
- Remote code：**No, I am not using remote code**
- Data collection：9 类全部**不勾选**
- Privacy policy URL：`https://lr3699.github.io/json-formatter-pro/privacy.html`

---

## 中文版文案（备用，添加 zh-CN 语言时使用）

## 基本信息

| 字段 | 内容 |
| --- | --- |
| Extension name | JSON 格式化查看器 - JSON Formatter Pro |
| Category | Developer tools |
| Supported languages | 中文（简体） |
| Mature content | 否 |
| Remote code | 未使用 |
| Data collection | 不收集任何数据 |

## Short description（manifest 里已写，商店自动读取）

```
自动美化网页中的 JSON：语法高亮、可折叠树、搜索定位、路径复制、转义保留/还原、浅色与深色主题。
```

## Description（详细描述，粘贴到 Store listings → Description）

```
打开接口地址，看到的是一大坨挤在一起的 JSON 字符串？本扩展会把它变成一张可以逐层展开的树。

安装后无需任何配置：当你访问的页面返回 JSON 时，它会自动接管渲染，把原始文本替换成带语法高亮的可折叠视图。

■ 核心功能

· 自动识别并美化
  支持 application/json、application/*+json 等 JSON 响应类型，打开即自动格式化。text/plain 返回的 JSON 也可选择自动格式化。

· 清晰的语法高亮
  键名加粗加深、字符串、数字、布尔值与 null 分色显示，层级缩进一目了然。内置浅色与深色两套主题，可跟随系统自动切换。

· 可折叠的树形结构
  任意节点可单独折叠展开，也可以一键全部折叠/全部展开，或直接「展开到第 N 层」。折叠的节点会显示「… 13 个字段」这样的摘要。

· 搜索定位
  在工具栏搜索框中输入关键词，实时匹配所有键名与值（包括被转义的内容），显示「3/11」命中计数，支持上下跳转，并自动展开命中所在的路径、高亮标记命中片段。

· 复制 JSONPath
  点击任意键名，直接复制该字段的完整路径，例如 $.data.list[0].orderId。点击值则复制值本身。

· 保留转义 / 还原转义
  默认保留源码写法，"a\nb" 就显示成 \n 两个字符；取消勾选则还原为真实的换行、中文等字符。看接口原始报文时非常有用。

· 美化 / 压缩 与导出
  一键切换美化输出与压缩输出，缩进可选 2 空格、4 空格或 Tab，并可复制到剪贴板或下载为 .json 文件。

· 数字精度零丢失
  使用自研解析器而非 JSON.parse，完整保留源码原文。像 600653836507516928 这类超出 JavaScript 安全整数范围的大整数（订单号、雪花 ID）不会被悄悄改成 600653836507516930。

· 出错也能定位
  JSON 格式非法时，给出精确的行号、列号，并用插入符标出出错位置。还提供「宽松解析」一键重试，自动处理注释、单引号、尾随逗号和未加引号的键名。

■ 多种入口

· 打开 JSON 页面自动格式化
· 点击工具栏图标，弹窗中一键格式化当前页面
· 页面右键菜单：格式化当前页面 / 格式化选中的内容
· 快捷键 Alt+Shift+J 快速切换格式化与还原
· 独立设置页，可自定义主题、缩进、字号、展开层级、行号等

■ 安全与隐私

· 不采集任何数据，不上传任何内容，不发起任何网络请求
· 不含远程代码，所有逻辑都在安装包内
· 查看器运行在 Shadow DOM 中，与网页样式完全隔离，既不会被网页影响，也不会污染网页
· 随时可点击「还原原文」恢复浏览器的默认显示

■ 适合谁

前后端开发者调试接口、测试同学核对返回字段、运维排查接口异常，以及任何需要快速读懂一段 JSON 的人。
```

## Search terms（搜索词，最多 7 个）

```
JSON
JSON formatter
JSON 格式化
JSON 查看器
JSON viewer
JSON 美化
接口调试
```

## Properties 页的补充字段

| 字段 | 建议值 |
| --- | --- |
| Website URL | 留空，或填你的项目主页/仓库地址 |
| Support contact details | 你的常用邮箱；建议在描述末尾附上，方便用户反馈 |
| Mature content | 否 |
| Does this extension collect personal information? | 否 |

## Certification testing notes（认证测试说明）

```
本扩展无需登录、无需账号即可测试。

测试步骤：
1. 安装后访问任意返回 JSON 的接口，例如 https://api.github.com/repos/microsoft/vscode
   页面应自动切换为格式化视图（可折叠树 + 语法高亮）。
2. 点击任意键名可复制 JSONPath；工具栏可搜索、切换主题、复制/下载格式化结果。
3. 点击工具栏「还原原文」可恢复浏览器默认的纯文本显示。
4. 点击工具栏图标打开弹窗，可手动「格式化当前页面」。
5. 扩展不发起任何网络请求，不采集任何数据（可在 DevTools Network 面板验证）。

若某接口未自动格式化，说明其 Content-Type 不是 JSON，属于预期行为。
```

## 隐私政策正文

见仓库根目录 [`PRIVACY.md`](../PRIVACY.md) —— 直接发布到任意可公开访问的 URL 即可。
