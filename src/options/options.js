(function () {
  'use strict';

  const NS = globalThis.__EDGE_JSON_FORMATTER__;
  const $ = (id) => document.getElementById(id);

  $('version').textContent = 'v' + chrome.runtime.getManifest().version;

  const NUMERIC = { maxAutoSize: true };

  const FIELDS = [
    { id: 'autoFormat', key: 'autoFormat', type: 'bool' },
    { id: 'autoFormatPlainText', key: 'autoFormatPlainText', type: 'bool' },
    { id: 'contextMenu', key: 'contextMenu', type: 'bool' },
    { id: 'maxAutoSize', key: 'maxAutoSize', type: 'int' },
    { id: 'theme', key: 'theme', type: 'str' },
    { id: 'indent', key: 'indent', type: 'indent' },
    { id: 'fontSize', key: 'fontSize', type: 'int' },
    { id: 'monoFont', key: 'monoFont', type: 'bool' },
    { id: 'lineNumbers', key: 'lineNumbers', type: 'bool' },
    { id: 'sortKeys', key: 'sortKeys', type: 'bool' },
    { id: 'keepEscape', key: 'keepEscape', type: 'bool' }
  ];

  const toastEl = $('toast');
  let toastTimer = null;

  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 1500);
  }

  let settings = Object.assign({}, NS.DEFAULTS);

  function readField(field) {
    const node = $(field.id);
    if (!node) return undefined;
    switch (field.type) {
      case 'bool': return node.checked;
      case 'int': return parseInt(node.value, 10);
      case 'indent':
        return node.value === 'tab' ? 'tab' : parseInt(node.value, 10);
      default: return node.value;
    }
  }

  function writeField(field, value) {
    const node = $(field.id);
    if (!node) return;
    if (field.type === 'bool') node.checked = !!value;
    else node.value = String(value);
  }

  function notifyTabs(patch) {
    chrome.tabs.query({}, (tabs) => {
      if (!tabs) return;
      for (const tab of tabs) {
        if (tab.id === undefined) continue;
        chrome.tabs.sendMessage(
          tab.id,
          { type: 'JF_SETTINGS_CHANGED', settings: Object.assign({}, settings, patch) },
          () => void chrome.runtime.lastError
        );
      }
    });
  }

  for (const field of FIELDS) {
    const node = $(field.id);
    if (!node) continue;
    node.addEventListener('change', () => {
      const value = readField(field);
      const patch = {};
      patch[field.key] = value;
      settings = Object.assign({}, settings, patch);
      NS.saveSettings(patch).then(() => {
        toast('设置已保存');
        notifyTabs(patch);
      });
      void NUMERIC;
    });
  }

  $('btnOpenEditor').addEventListener('click', () => {
    NS.openEditor();
  });

  NS.loadSettings().then((loaded) => {
    settings = Object.assign({}, NS.DEFAULTS, loaded);
    for (const field of FIELDS) writeField(field, settings[field.key]);
  });
})();
