# 上架 Microsoft Edge 加载项商店 · 完整流程

> 依据 Microsoft 官方文档《Publish a Microsoft Edge extension》整理（2026-09 核对）。
> 参考：https://learn.microsoft.com/microsoft-edge/extensions/publish/publish-extension

## 提交结果（2026-09-20 已完成）

**已提交，状态：In review（审核中）。**

| 项 | 值 |
| --- | --- |
| 产品 ID | `b5797b76-ba71-40f0-abd2-b1248f932cf1` |
| Store ID | `0RDCK9ZTJXV2` |
| CRX ID | `lckjaaokeleokmdnjfagooohghjflcn` |
| 版本 | 1.0.0 |
| 分类 | Developer Tools |
| 可见性 | Public（全部市场） |
| 商店语言 | English (United States) |
| 认证说明 | 1488 / 2000 字符，已填 |
| 商店状态页 | <https://partner.microsoft.com/en-us/dashboard/microsoftedge/b5797b76-ba71-40f0-abd2-b1248f932cf1> |

已完成的 6 个步骤（左侧导航全部打勾）：Extension overview ✓ / Packages ✓ /
Availability ✓ / Properties ✓ / Privacy ✓ / Store listings ✓。

等待结果：**最长 7 个工作日**，结果发到注册邮箱 `lr3699@163.com`。
通过后 URL 才会出现，届时形如
`https://microsoftedge.microsoft.com/addons/detail/0RDCK9ZTJXV2`。

> 关于语言：manifest 里硬编码中文、没有 `_locales`，所以 Partner Center 只识别出
> **English (United States)** 一种语言，商店文案因此用英文撰写（与声明语言一致，
> 审核更顺）。扩展名仍按 manifest 显示为「JSON 格式化查看器 - JSON Formatter Pro」。
> 若想补一个中文（简体）商店页，在 Partner Center 的 Store listings 页
> 「Add a language」里加 zh-CN 再单独填一遍即可，不影响本次审核。

### 待提交的更新：v1.1.0（本地已就绪，等 1.0.0 审核结束）

商店里的 1.0.0 正在审核，不要再提交一次「同版本更新」。等 1.0.0 通过后，
用下面的包走 **Update** 流程（Overview → Update → Packages → 上传 → Store listings 可顺带补文案 → Submit）：

| 项 | 值 |
| --- | --- |
| 上传包 | `dist/json-formatter-pro-1.1.0.zip` |
| 本版新增 | 粘贴 JSON 格式化编辑页（弹窗 / 右键 / 设置页三个入口，逐行入场动效） |
| 本版修复 | 正文字号与笔画（13px/400 → 15px/500）、右键菜单开关改后不生效 |
| 权限变化 | **无**（未新增任何权限，`permissions` 与 `host_permissions` 与 1.0.0 完全一致） |

因为权限没变，更新审核通常比首次上架快，且不需要重填隐私问卷——
Privacy 页保持原样即可，只需在 `Packages` 换包、必要时在 `Store listings` 里
把描述里的功能清单补一句「paste your own JSON」。英文描述建议追加：

> Paste your own JSON too — a built-in editor formats anything you copy from logs,
> chat, or a terminal, with the same collapsible tree and syntax highlighting.

（`docs/store-listing.md` 里有完整文案。）


---

## 背景说明

注册 Partner Center 开发者账号、签署开发者协议这两件事**必须由账号本人完成**
（涉及身份信息与协议签署），其余步骤都可以自动化代做。

本次流程：先由我在浏览器里逐步完成 6 个表单页的填写与提交，账号注册由你本人完成。

---

## 第 0 步：准备物（已完成）

| 物料 | 位置 | 说明 |
| --- | --- | --- |
| 扩展包 | `dist/json-formatter-pro-1.0.0.zip` | 根目录即 `manifest.json`，可直接上传 |
| 商店图标 | `icons/store-icon-300.png` | 300×300 PNG |
| 截图（≥1 张） | `docs/shots/shot-light.png` | 1280×800，符合要求 |
| 截图 2 | `docs/shots/shot-dark.png` | 深色主题 |
| 截图 3 | `docs/shots/shot-search.png` | 搜索定位功能 |
| 商店文案 | `docs/store-listing.md` | 直接复制粘贴 |
| 隐私政策 | `PRIVACY.md` / `site/privacy.html` | **已上线**，见下方 URL |

上传前建议先跑一遍体检，它会检查 ZIP 分隔符、manifest 字段长度上限、图标与脚本引用是否齐全：

```bash
node tools/verify-package.js
```

### 隐私政策 URL —— 已就绪，直接复制

商店要求：**只要你声明「不收集数据」，仍然必须提供一个隐私政策链接**。已经上线，无需再操作：

```
https://lr3699.github.io/json-formatter-pro/privacy.html
```

（同一站点还带了功能介绍页：<https://lr3699.github.io/json-formatter-pro/>）

这条是你自己 GitHub 账号下的 GitHub Pages，仓库为 `github.com/lr3699/json-formatter-pro`
（Public，Pages 源为 `main` / `(root)`）。已验证 `/`、`/privacy.html`、`/style.css` 均返回 200。

备份链接（内置托管，若前者因故不可用可临时顶替）：

```
https://json-formatter-privacy.app.workbuddy.host/privacy.html
```

**以后要更新站点内容**：改完 `site/` 下的文件后，网页版最省事 ——
仓库页 → Add file → Upload files，把改动的文件传上去提交即可。

> ⚠ 首次是用网页版上传的，所以**本地 `site/` 里的 git 历史与 GitHub 上那条提交不是同一条**。
> 若要改用本地 git 推送，先执行一次 `cd site && git pull --rebase origin main` 对齐历史，
> 否则直接 push 会被拒。凭据也需要先配（`git push` 首次会弹浏览器让你登录 GitHub）。


---

## 第 1 步：注册开发者账号

1. 打开 <https://partner.microsoft.com/dashboard/microsoftedge/>，用你的微软账号登录。
2. 首次进入会引导注册 **Microsoft Edge 计划**。
3. 填写：
   - **Account country/region**：居住地或公司所在地（注册后不可改）。
   - **Account type**：个人选 *Individual*（验证更快，只需校验发布者名称可用）；公司选 *Company*（需提交营业执照等资料，可能接到微软验证电话，耗时数天到数周）。
   - **Publisher display name**：商店上展示的开发者名称，最长 50 字符。
   - **Contact details**：微软联系你的邮箱（公司账号须用企业域名邮箱）。
4. 勾选接受《App Developer Agreement》，点 **Finish**。
5. 等待账号验证邮件。Edge 扩展的开发者注册**本身是免费的**（网上流传的 19 美元是旧版 Microsoft Store 应用的上架费，不适用于 Edge 加载项）。

> 验证期间你可以继续做第 2–8 步的准备工作。

---

## 第 2 步：创建扩展

Partner Center 首页 → **Workspaces** 区域点 **Edge** 卡片 → 概览页点 **Create new extension**。

---

## 第 3 步：上传包

1. 拖入 `dist/json-formatter-pro-1.0.0.zip`。
2. 等待自动校验，通过后进入 **Packages** 页面。
3. 校验失败一般是 manifest 字段问题，把报错贴给我即可定位。

---

## 第 4 步：可用性

- **Visibility**：先选 **Hidden**（只有拿到链接的人能安装）做灰度验证，稳定后再改 **Public**。
- **Markets**：默认全部市场；只想面向国内可选中国。

---

## 第 5 步：属性

| 字段 | 建议填写 |
| --- | --- |
| Category | **Developer tools** |
| Website URL | 可留空或填你的项目主页 |
| Support contact | 你的邮箱 |
| Mature content | 否 |

---

## 第 6 步：隐私信息

这一页是审核最容易卡住的地方，逐项对应如下：

- **State the extension's purpose（说明用途）**
  > 识别网页返回的 JSON 内容并渲染为可折叠、带语法高亮的查看器，帮助开发者阅读接口返回数据。

- **Justify permissions（逐项说明权限）**
  > `storage` — 保存用户的显示偏好（主题、缩进、字号等）。
  > `contextMenus` — 提供「格式化当前页面 / 选中内容」的右键入口。
  > `activeTab` — 让工具栏弹窗能与当前标签页通信。
  > `<all_urls>` — 内容脚本必须在目标页面加载时才能判断该页是否为 JSON 响应，从而决定是否接管渲染。扩展仅读取本页文本，不发送任何数据。

- **Remote code（远程代码）**：**No / 未使用**。所有代码都打包在安装包内。

- **Data usage（数据使用）**：全部勾选 **不收集**。本扩展不采集任何数据、不做网络请求、不共享给第三方。

- **Privacy policy URL**：填第 0 步准备好的链接。

---

## 第 7 步：商店一览

**Store listings → 该语言行点 Edit details**，逐项填写：

- Extension name：取自 manifest，只读
- **Description**：粘贴详细描述（≤ 10000 字符）——本次用的是英文版
- **Extension logo**：上传 `icons/store-icon-300.png`（300×300，必需）
- **Screenshots**：本次上传 6 张 1280×800（`docs/shots/` 下的
  `shot-light` / `shot-dark` / `shot-search` / `shot-lines` / `shot-compact` / `e2e-packaged`）
- **Search terms**：7 个（JSON、JSON formatter、JSON viewer、JSON pretty print、
  API response viewer、JSON highlighter、JSON tree，合计 15 个单词 ≤ 21 上限）

> 语言取决于 manifest：带 `_locales` + `__MSG_xxx__` 占位符才会出现多语言，
> 否则 Partner Center 只给一个默认行（本次是 English (United States)）。
> 只要**填满任意一种语言**就能继续提交，其余语言可以以后再补。
> 用 `Add a language` 可加中文（简体）单独填一份，不影响已提交的审核。

---

## 第 8 步：认证说明与提交

**Certification testing notes（给测试人员的说明）** 建议填：

```
本扩展无需登录、无需账号即可测试。

测试步骤：
1. 安装后访问任意返回 JSON 的接口，例如 https://api.github.com/repos/microsoft/edge-extensions
   页面应自动切换为格式化视图（可折叠树 + 语法高亮）。
2. 点击任意键名可复制 JSONPath；工具栏可搜索、切换主题、复制/下载格式化结果。
3. 点击工具栏「还原原文」可恢复浏览器默认的纯文本显示。
4. 点击工具栏图标打开弹窗，可手动「格式化当前页面」。
5. 扩展不发起任何网络请求，不采集任何数据。

若某接口未自动格式化，说明其 Content-Type 不是 JSON，属于预期行为。
```

填完点 **Publish** → 进入认证，**最长 7 个工作日** → 通过后状态变为 **In the Store**。

---

## 常见被拒原因与规避

| 拒因 | 本项目的状态 |
| --- | --- |
| 权限未逐项说明 | 已在第 6 步给出逐项说明文案 |
| 缺少隐私政策链接 | `PRIVACY.md` 已备好，只需发布成 URL |
| 描述与实际功能不符 | `docs/store-listing.md` 仅陈述已实现的功能 |
| 含未声明的隐藏功能 | 无埋点、无统计、无远程代码 |
| 使用了 Manifest V2 | 本扩展为 MV3 |
| 访问了与功能无关的主机 | `host_permissions` 仅为内容脚本注入所需 |

---

## 提交后

- 认证期间可以修改资料，但会重新排队。
- 通过后：`edge://extensions/` 会随浏览器自动更新已安装版本（商店版本）。
- 发新版：改 `manifest.json` 里的 `version` → 重新 `tools/build.ps1` → 在 Partner Center 的 **Packages** 页上传新的 zip → 提交更新。
