# Chrome Web Store 上架清单（JSON Duo 1.1.3）

> Chrome 网上应用店与 Edge Add-ons 相互独立：包可以复用，但开发者账号、
> 商品 ID、商店页、审核全部要重来一遍。本文档是 Chrome 侧的完整填写对照表。

## 0. 账号前提（需要用户本人操作，无法代做）

| 事项 | 说明 |
| --- | --- |
| Google 账号 | 用哪个账号注册开发者，以后扩展都挂在它名下，邮箱注册后不可改 |
| 两步验证（2FA） | **强制**：Google 账号未开 2FA 无法发布 |
| 开发者注册费 | **一次性 $5**，信用卡 / Google Pay，注册页直接付，永久有效（一个账号可发约 20 个扩展） |
| 联系邮箱 | 注册后验证，审核结果都发到这里 |
| 发布者显示名称 | 商店页展示的开发者名，建议与 Edge 侧一致 |
| 交易者声明（EU DSA） | 免费、无商业化 → 选 **非交易者（non-trader）** |

注册入口：<https://chrome.google.com/webstore/devconsole>

## 1. 上传包

- 文件：`dist/json-duo-1.1.3.zip`（74.4 KB，与 Edge 同包，manifest 在 zip 根）
- 兼容性已核对：MV3 / service worker / `chrome.action.onClicked`（无 popup）/
  `runtime.getContexts`（Chrome 116+，老版本有降级分支）/ 无远程代码 / 无 eval
- 名称上限 75 字符：`JSON Duo` ✔（manifest i18n：zh_CN 默认）

## 2. Store listing（商店页）

| 字段 | 内容 |
| --- | --- |
| Item name | JSON Duo（取自 manifest） |
| **Summary（摘要，≤132 字符）** | 双栏 JSON 工作台：左栏粘贴原文、右栏实时预览，网页 JSON 自动美化成可折叠的语法高亮树，纯本地运行 |
| Category（类别） | Developer Tools（开发者工具） |
| Language（语言） | 中文（简体）—— 与 manifest `default_locale: zh_CN` 一致 |
| Homepage URL | https://lr3699.github.io/json-formatter-pro/ |
| Support URL | https://lr3699.github.io/json-formatter-pro/ （或 GitHub 仓库 issues） |
| Privacy policy URL | https://lr3699.github.io/json-formatter-pro/privacy.html |

### Detailed description（详细描述，直接粘贴）

与 Edge 主文案一致，见 [`store-listing.md`](store-listing.md) 的「Description」代码块
（约 1222 字符，上限 16000）。粘贴时 CWS 会剥离 Markdown，原文已是纯文本友好格式。

### 截图（1–5 张，1280×800，PNG/JPG，不能带透明通道）

按顺序上传以下 5 张（均在 `docs/shots/`、`docs/` 下）：

1. `docs/editor-done.png` —— 粘贴编辑页：双栏 + 实时结果
2. `docs/shots/shot-light.png` —— 浅色主题的自动格式化视图
3. `docs/shots/shot-dark.png` —— 深色主题
4. `docs/shots/shot-compact.png` —— 紧凑模式
5. `docs/editor-dark.png` —— 深色编辑页

> Edge 用过的 `shot-toolbar.png`（2560×440）不符合 Chrome 尺寸要求，不要传。

### 推广图（`docs/chrome-assets/`）

| 资产 | 尺寸 | 文件 |
| --- | --- | --- |
| Small promo tile（小推广图，强烈建议） | 440×280 | `promo-small-440x280.png` |
| Large promo tile（大推广图，可选） | 920×680 | `promo-large-920x680.png` |
| Marquee promo tile（横幅，可选） | 1400×560 | `promo-marquee-1400x560.png` |

重新生成：`python tools/shoot_promo.py`（源文件 `docs/promo-tiles.html`）。

## 3. Privacy（隐私）页

| 字段 | 填写内容 |
| --- | --- |
| **Single purpose（单一用途）** | 识别网页返回的 JSON 内容，并将其渲染为可折叠、带语法高亮的查看器，帮助开发者阅读与调试接口返回数据。 |
| Permission justification — `storage` | 保存用户的显示偏好（主题、缩进宽度、字号、是否自动折叠等）到浏览器本地存储，不上传任何服务器。 |
| Permission justification — `contextMenus` | 在页面右键菜单中提供「格式化当前页面 / 格式化选中内容 / 打开编辑页」入口，方便快速调用格式化功能。 |
| Permission justification — `activeTab` | 用户点击工具栏图标时与当前活动标签页通信，以格式化该页面的 JSON 内容。 |
| Permission justification — Host permission（所有网站） | 扩展在页面加载时读取页面文本，以判断该页面是否为 JSON 响应，从而决定是否接管渲染为格式化视图；所有解析均在本地完成，不收集、不发送任何数据。 |
| Remote code | No, I am not using remote code |
| 数据使用披露（9 项） | 全部不勾选（不收集任何个人数据、健康、财务、通讯录、浏览活动、位置等） |
| Certification 声明 | 勾选确认遵守开发者计划政策 |

> 注意：`<all_urls>` 会触发 CWS 的 in-depth review，审核时间可能从 1–3 天延长到数周，属正常现象。

## 4. Distribution（分发）

- Visibility：**Public**
- 地区：全部
- 免费（Free）

## 5. Review notes（审核备注，提交页填写）

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

## 6. 提交流程（Dashboard 顺序）

1. Package → 上传 `json-duo-1.1.3.zip`（首次提交自动跑安装检测）
2. Store listing → 名称/摘要/描述/截图/推广图/类别/语言
3. Privacy → 单一用途 + 4 条权限说明 + 数据披露 + 隐私政策 URL
4. Distribution → Public + 全地区
5. 提交审核（Submit for review）

## 7. 预期与后续

- 首次提交 + `<all_urls>` → 大概率人工审核，**1–3 天到数周**都有可能
- 审核结果发到注册邮箱；被拒会引用具体政策条款，改完可直接重新提交
- 上架后的商店链接形如
  `https://chromewebstore.google.com/detail/<slug>/<新ID>`
  （Chrome 的扩展 ID 与 Edge 的 `lckjaaoekeleokmdnjjfagoohghjflcn` 无关，以 Chrome 分配为准）
