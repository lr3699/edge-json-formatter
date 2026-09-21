# -*- coding: utf-8 -*-
"""检查 Partner Center Packages 页的 file input 状态，补发 change 事件，读包区域文本。"""
import sys
import time

sys.path.insert(0, r"C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts")
from cdp import CDPClient  # noqa: E402

FIND_INPUT_JS = """
(function () {
  var found = null;
  function walk(root, depth) {
    if (depth > 16 || found) return;
    var nodes = root.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.shadowRoot) walk(el.shadowRoot, depth + 1);
      var tag = (el.tagName || '').toLowerCase();
      if (tag === 'input' && el.type === 'file') { found = el; return; }
    }
  }
  walk(document, 0);
  if (!found) return 'NO_INPUT';
  var n = (found.files && found.files.length) || 0;
  try {
    found.dispatchEvent(new Event('input', { bubbles: true }));
    found.dispatchEvent(new Event('change', { bubbles: true }));
  } catch (e) {}
  return JSON.stringify({ files: n, name: n ? found.files[0].name : '' });
})()
"""


def main():
    c = CDPClient(host="127.0.0.1", port=9222, timeout=90)
    try:
        c.ensure_page(url_contains="/packages")
        c.send("Page.enable")
        state = c.evaluate(FIND_INPUT_JS).get("value")
        print("input state:", state)
        time.sleep(8)
        txt = c.evaluate(
            'document.body.innerText.replace(/\\s+/g, " ")'
        ).get("value") or ""
        idx = txt.find("Your current package")
        print("pkg area:", txt[idx:idx + 350] if idx >= 0 else txt[:350])
    finally:
        c.close()


if __name__ == "__main__":
    main()
