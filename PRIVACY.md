# 隐私政策 / Privacy Policy

**扩展名称：** JSON Duo（双栏 JSON 工作台）
**最后更新：** 2026-09-20

## 一句话总结

本扩展**不采集、不存储、不传输**任何用户数据。所有处理都在你的浏览器本地完成。

## 详细说明

### 1. 我们收集哪些数据

**不收集任何数据。** 具体而言：

- 不收集个人身份信息（姓名、邮箱、账号等）
- 不收集浏览历史、访问的网址或页面内容
- 不收集设备信息、地理位置、IP 地址
- 不使用 Cookie、指纹识别或任何追踪技术
- 不进行任何统计分析、埋点或 A/B 测试

### 2. 页面内容如何处理

当页面返回 JSON 时，扩展在**你本机浏览器的内存中**解析并渲染这些内容，用于提供格式化显示。
JSON 原文与解析结果**不会离开你的设备**，不会写入磁盘，也不会发送到任何服务器。

关闭标签页后，这些内容即从内存中释放。

### 3. 本地保存的数据

扩展仅使用浏览器自带的 `chrome.storage.sync` 保存你的**显示偏好**，包括：

- 是否自动格式化
- 默认主题（浅色 / 深色 / 跟随系统）
- 缩进宽度、字号、是否显示行号
- 是否默认保留转义
- 自动格式化的体积上限

这些偏好不包含任何个人信息。若你登录了浏览器账号，浏览器自身的同步机制可能在其服务器上同步这些设置——
这是浏览器厂商提供的能力，与本扩展无关，且其中不含任何可识别你身份的内容。

### 4. 网络访问

本扩展**不发起任何网络请求**，不加载任何远程脚本、样式或资源，所有代码都打包在安装包内。

### 5. 第三方共享

**无。** 我们没有任何第三方服务商，也不会向任何第三方出售、出租或共享数据。

### 6. 权限用途

| 权限 | 用途 | 是否涉及数据外传 |
| --- | --- | --- |
| `storage` | 保存上述显示偏好 | 否 |
| `contextMenus` | 提供右键菜单入口 | 否 |
| `activeTab` | 弹窗与当前标签页通信 | 否 |
| `<all_urls>` 主机权限 | 内容脚本需要在页面加载时判断是否为 JSON 并接管渲染 | 否 |

### 7. 儿童隐私

本扩展不面向儿童，也不收集任何年龄段用户的数据。

### 8. 政策变更

若本政策发生变更，我们会更新本文件的「最后更新」日期，并在扩展更新说明中注明。

### 9. 联系方式

如有隐私相关问题，请通过商店页面提供的开发者联系方式与我们联系。

---

## English Summary

This extension collects **no data whatsoever**. It performs all JSON parsing and rendering
locally in your browser's memory. Page contents never leave your device. It stores only your
display preferences (theme, indent, font size, toggles) in `chrome.storage.sync`, makes no
network requests, bundles no remote code, and shares nothing with third parties.
