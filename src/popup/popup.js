(function () {
  'use strict';

  const NS = globalThis.__EDGE_JSON_FORMATTER__;

  const $ = (id) => document.getElementById(id);
  const dot = $('dot');
  const statusText = $('statusText');
  const btnFormat = $('btnFormat');
  const btnRestore = $('btnRestore');

  let activeTab = null;

  $('version').textContent = 'v' + chrome.runtime.getManifest().version;

  function setStatus(kind, text) {
    dot.className = 'dot' + (kind ? ' ' + kind : '');
    statusText.textContent = text;
  }

  function queryActiveTab() {
    return new Promise((resolve) => {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        resolve(tabs && tabs[0] ? tabs[0] : null);
      });
    });
  }

  function send(message) {
    return new Promise((resolve) => {
      if (!activeTab || activeTab.id === undefined) {
        resolve({ ok: false, reason: '没有可用的标签页' });
        return;
      }
      chrome.tabs.sendMessage(activeTab.id, message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, reason: '当前页面无法使用（可能是浏览器内置页面或商店页面）' });
          return;
        }
        resolve(response || { ok: false, reason: '页面没有响应' });
      });
    });
  }

  function refreshStatus() {
    setStatus('', '正在检测当前页面…');
    btnFormat.disabled = true;
    btnRestore.disabled = true;

    send({ type: 'JF_PING' }).then((res) => {
      if (!res || !res.ok) {
        setStatus('warn', res && res.reason ? res.reason : '无法检测当前页面');
        return;
      }
      if (res.formatted) {
        setStatus('ok', '已格式化，正在显示 JSON 视图');
        btnFormat.disabled = true;
        btnRestore.disabled = false;
      } else if (res.isJson) {
        setStatus('ok', '检测到 JSON 内容，可一键格式化');
        btnFormat.disabled = false;
        btnRestore.disabled = true;
      } else {
        setStatus('warn', res.reason || '当前页面不是 JSON 内容');
      }
    });
  }

  btnFormat.addEventListener('click', () => {
    btnFormat.disabled = true;
    send({ type: 'JF_FORMAT' }).then((res) => {
      if (!res || !res.ok) {
        setStatus('warn', (res && res.reason) || '格式化失败');
        btnFormat.disabled = false;
        return;
      }
      setStatus('ok', '已格式化' + (res.lenient ? '（使用了宽松解析）' : ''));
      btnRestore.disabled = false;
    });
  });

  btnRestore.addEventListener('click', () => {
    send({ type: 'JF_RESTORE' }).then(() => refreshStatus());
  });

  $('btnOptions').addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
  });

  /**
   * 「粘贴 JSON 格式化」：打开独立编辑页（复用已打开的页面）。
   */
  $('btnPaste').addEventListener('click', () => {
    NS.openEditor();
    window.close();
  });

  // ---- 设置项 ----
  let settings = Object.assign({}, NS.DEFAULTS);

  function bindCheckbox(id, key) {
    const box = $(id);
    box.addEventListener('change', () => {
      const patch = {};
      patch[key] = box.checked;
      settings = Object.assign(settings, patch);
      NS.saveSettings(patch).then(() => notifyTab(patch));
    });
  }

  function bindSelect(id, key, cast) {
    const sel = $(id);
    sel.addEventListener('change', () => {
      const patch = {};
      patch[key] = cast ? cast(sel.value) : sel.value;
      settings = Object.assign(settings, patch);
      NS.saveSettings(patch).then(() => notifyTab(patch));
    });
  }

  function notifyTab(patch) {
    if (!activeTab || activeTab.id === undefined) return;
    chrome.tabs.sendMessage(
      activeTab.id,
      { type: 'JF_SETTINGS_CHANGED', settings: settings },
      () => void chrome.runtime.lastError
    );
    void patch;
  }

  bindCheckbox('autoFormat', 'autoFormat');
  bindCheckbox('keepEscape', 'keepEscape');
  bindSelect('theme', 'theme');
  bindSelect('indent', 'indent', (v) => (v === 'tab' ? 'tab' : parseInt(v, 10)));

  NS.loadSettings().then((loaded) => {
    settings = Object.assign({}, NS.DEFAULTS, loaded);
    $('autoFormat').checked = !!settings.autoFormat;
    $('keepEscape').checked = !!settings.keepEscape;
    $('theme').value = settings.theme;
    $('indent').value = String(settings.indent);
    queryActiveTab().then((tab) => {
      activeTab = tab;
      refreshStatus();
    });
  });
})();
