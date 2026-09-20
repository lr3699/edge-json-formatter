# 商店一览文案（可直接复制到 Partner Center）

> 本扩展通过 manifest 的 `default_locale: zh_CN` + `_locales` i18n 提供中英文，
> Partner Center 会识别出「中文（简体）」与「英文」两种语言。下方中文为默认主语言。
> 扩展名统一为 **JSON Duo**。

## 基本信息

| 字段 | 内容 |
| --- | --- |
| Extension name | JSON Duo（取自 manifest，只读） |
| Short description | 双栏 JSON 工作台：左栏粘贴原文、右栏实时预览（取自 manifest.description） |
| Category | Developer tools |
| Supported languages | 中文（简体）+ English |
| Mature content | 否 |
| Remote code | 未使用 |
| Data collection | 不收集任何数据 |

## Description（详细描述 · 中文主文案，粘贴到 Store listings → Description）

```
JSON Duo 是一把「双栏」的 JSON 瑞士军刀：左边粘贴、右边实时预览，网页上的 JSON 也能自动接手。

不用再眯着眼看那一大坨挤在一行的 minified JSON。装上之后，凡是网页返回的 JSON，都会自动变成一张可以逐层展开、带语法高亮的树；你自己复制下来的 JSON，也只需 Ctrl+V 贴进内置编辑页，右栏立刻出结果。

■ 核心能力

· 自动识别，打开即美化
  自动接管 application/json、application/*+json 等响应类型；text/plain 里藏着的 JSON 也可一键自动格式化。无需任何配置。

· 双栏工作台
  左栏粘贴原文（支持 Ctrl+V、拖入 .json/.txt、点「示例」），右栏实时预览。输入防抖 220ms，边改边看，还能按 F 一键全屏沉浸。

· 清晰的语法高亮
  键名、字符串、数字、布尔值、null 分色显示，层级缩进一目了然。内置浅色 / 深色两套主题，可跟随系统自动切换。

· 可折叠的树
  任意节点单独折叠展开；格式化后默认全展开。折叠节点会显示「… 13 个字段」这样的摘要，超大 JSON 分批渲染，滚到哪看到哪。

· 一键复制 JSONPath
  点任意键名复制完整路径（如 data.list[0].orderId），点值则复制值本身。定位字段、写断言、写代码都方便。

· 保留 / 还原转义
  默认原样显示 \n、\uXXXX 等转义写法，看清接口原始报文；一键关闭即可还原为真实字符。

· 美化 / 压缩 与导出
  工具栏只留 5 个按钮：保留转义、主题、美化/压缩、复制、下载。切换压缩即刻收成单行，复制或下载为 .json 一步到位。

· 数字精度零丢失
  自研解析器（非 JSON.parse），完整保留源码原文。600653836507516928 这种超出 JS 安全整数范围的大整数（订单号、雪花 ID）不会被悄悄改错。

· 出错也能定位
  JSON 非法时给出精确行号、列号，并用插入符标出出错位置；还有「宽松解析」一键重试，自动容忍注释、单引号、尾随逗号和裸键名。

■ 入口多样

· 打开 JSON 页面自动格式化
· 点击工具栏图标，直接进入内置编辑页
· 页面右键菜单：格式化当前页面 / 格式化选中内容 / 打开编辑页
· 快捷键 Alt+Shift+J 快速切换格式化与还原
· 独立设置页，自定义主题、缩进、字号、行号等

■ 安全与隐私

· 不采集任何数据，不上传任何内容，不发起任何网络请求
· 不含远程代码，所有逻辑都在安装包内
· 查看器运行在 Shadow DOM 中，与网页样式完全隔离，互不污染
· 随时还原原文，恢复浏览器默认显示

■ 适合谁

前后端开发者调试接口、测试同学核对返回字段、运维排查接口异常，以及任何需要快速读懂一段 JSON 的人。
```

## Search terms（搜索词，最多 7 个）

```
JSON
JSON 格式化
JSON 查看器
JSON formatter
JSON viewer
JSON 美化
接口调试
```

## 素材

- Extension logo：`icons/store-icon-300.png`（300×300）
- Screenshots（6 张，1280×800）：`docs/shots/` 下的
  `shot-light` / `shot-dark` / `shot-toolbar` / `shot-compact` /
  `../editor-done` / `../editor-dark`（重拍：`python tools/shoot.py`）

## Properties 页的补充字段

| 字段 | 建议值 |
| --- | --- |
| Website URL | 留空，或填项目主页/仓库地址 |
| Support contact details | 常用邮箱；建议在描述末尾附上，方便用户反馈 |
| Mature content | 否 |
| Does this extension collect personal information? | 否 |

## Certification testing notes（认证测试说明 · 中文）

```
本扩展无需登录、无需账号即可测试。

测试步骤：
1. 安装后访问任意返回 JSON 的接口，例如 https://api.github.com/repos/microsoft/vscode
   页面应自动切换为格式化视图（可折叠树 + 语法高亮，默认全展开）。
2. 点击工具栏图标，直接打开内置「粘贴 JSON 格式化」编辑页，粘贴一段 JSON 右栏即出结果。
3. 工具栏 5 个按钮：保留转义、主题、美化/压缩、复制、下载，切换即时生效。
4. 点击任意键名可复制 JSONPath。
5. 扩展不发起任何网络请求、不采集任何数据（可在 DevTools Network 面板验证）。

若某接口未自动格式化，说明其 Content-Type 不是 JSON，属于预期行为。
```

## Privacy 页实际填写内容

- Single purpose：识别网页返回的 JSON 内容，并将其渲染为可折叠、带语法高亮的查看器，帮助开发者阅读与调试接口返回数据。
- `storage`：保存用户的显示偏好（主题、缩进宽度、字号、是否自动折叠等本地设置），仅写入浏览器本地存储，不上传任何服务器。
- `contextMenus`：在页面右键菜单中提供「格式化 / 折叠 JSON」入口，方便用户对当前页面或选中内容快速调用扩展的格式化功能。
- `activeTab`：用户点击工具栏图标时，让扩展能够读取并与当前活动标签页通信，从而格式化该页面的 JSON 内容。
- Host permission：扩展需要在页面加载时读取页面文本，以判断该页面是否为 JSON 响应，从而决定是否接管渲染。所有解析均在本地完成，不收集、不发送任何数据。
- Remote code：**No, I am not using remote code**
- Data collection：9 类全部**不勾选**
- Privacy policy URL：`https://lr3699.github.io/json-formatter-pro/privacy.html`

## 隐私政策正文

见仓库根目录 [`PRIVACY.md`](../PRIVACY.md) —— 直接发布到任意可公开访问的 URL 即可。

---

## 英文版文案（备用，Add a language 添加 English 时使用）

### Description

```
JSON Duo is a dual-pane JSON workbench: paste raw JSON on the left, see it rendered live on the right — and auto-takeover for JSON on any page.

Stop squinting at one endless line of minified JSON. Any JSON response in your browser is instantly turned into a collapsible, syntax-highlighted tree; anything you copied from logs, chat or a terminal goes into the built-in editor with live preview.

FEATURES
• Auto-detection — opens and beautifies application/json and *+json responses instantly
• Dual-pane editor — paste on the left, live preview on the right, press F for fullscreen focus
• Syntax highlighting with light and dark themes (follows system)
• Collapsible tree, fully expanded by default; batch rendering for huge payloads
• One-click JSONPath copy — data.list[0].orderId and friends
• Keep or restore \uXXXX escapes
• 5-button toolbar: escape / theme / pretty-compact / copy / download
• Zero precision loss — a custom parser keeps big integers like 600653836507516928 intact
• Precise error location with line/column and caret, plus lenient retry

PRIVACY
100% local. No data collected, nothing uploaded, no network requests, no remote code.
```

### Search terms

```
JSON
JSON formatter
JSON viewer
JSON pretty print
API response viewer
JSON highlighter
JSON tree
```

### Notes for certification

```
JSON Duo is a client-side JSON viewer. No account, credentials or special setup is required.

HOW TO TEST
1. Install and open a public JSON endpoint, e.g. https://jsonplaceholder.typicode.com/todos/1 — it should render as a collapsible, syntax-highlighted tree.
2. Click the toolbar icon to open the built-in editor; paste any JSON to see the live preview.
3. Use the 5-button toolbar: escape, theme, pretty/compact, copy, download.
4. Click a key to copy its JSONPath.
5. Press Alt+Shift+J or use the right-click menu to toggle formatting.

PERMISSIONS
- storage: saves display preferences locally only.
- contextMenus: adds right-click format entries.
- activeTab: lets the toolbar icon open and communicate with the current tab.
- <all_urls>: the content script reads page text to detect JSON responses.

All parsing is local. No data is collected or transmitted; no remote code.
```
