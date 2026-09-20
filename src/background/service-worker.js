/**
 * Service worker：右键菜单、快捷键、安装初始化。
 */
importScripts('../shared/defaults.js');

const NS = globalThis.__EDGE_JSON_FORMATTER__;

const MENU_PAGE = 'jf-format-page';
const MENU_SELECTION = 'jf-format-selection';
const MENU_EDITOR = 'jf-open-editor';

function createMenus(enabled) {
  chrome.contextMenus.removeAll(() => {
    if (!enabled) return;
    chrome.contextMenus.create({
      id: MENU_EDITOR,
      title: '粘贴 JSON 格式化（打开编辑页）',
      contexts: ['page', 'selection']
    });
    chrome.contextMenus.create({
      id: MENU_PAGE,
      title: '用 JSON 格式化查看当前页面',
      contexts: ['page']
    });
    chrome.contextMenus.create({
      id: MENU_SELECTION,
      title: 'JSON 格式化选中的内容',
      contexts: ['selection']
    });
  });
}

chrome.runtime.onInstalled.addListener((details) => {
  NS.loadSettings().then((settings) => {
    if (details.reason === 'install') {
      const patch = {};
      Object.keys(NS.DEFAULTS).forEach((k) => { patch[k] = NS.DEFAULTS[k]; });
      NS.saveSettings(patch);
    }
    createMenus(settings.contextMenu !== false);
  });
});

chrome.runtime.onStartup.addListener(() => {
  NS.loadSettings().then((settings) => {
    createMenus(settings.contextMenu !== false);
  });
});

/**
 * 设置项是平铺写入 storage 的（NS.saveSettings 直接用 key 作属性名），
 * 所以这里判断的是 changes.contextMenu，而不是某个聚合对象。
 */
chrome.storage.onChanged.addListener((changes) => {
  if (!changes || !changes.contextMenu) return;
  createMenus(changes.contextMenu.newValue !== false);
});

function sendToTab(tabId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, reason: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: false, reason: '页面没有响应' });
    });
  });
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === MENU_EDITOR) {
    NS.openEditor();
    return;
  }
  if (!tab || tab.id === undefined) return;
  if (info.menuItemId === MENU_PAGE) {
    sendToTab(tab.id, { type: 'JF_FORMAT' });
  } else if (info.menuItemId === MENU_SELECTION) {
    sendToTab(tab.id, { type: 'JF_FORMAT_TEXT', text: info.selectionText || '' });
  }
});

chrome.commands.onCommand.addListener((command, tab) => {
  if (command !== 'toggle-format') return;
  const tabId = tab && tab.id !== undefined
    ? tab.id
    : undefined;
  if (tabId === undefined) return;
  sendToTab(tabId, { type: 'JF_TOGGLE' });
});
