# -*- coding: utf-8 -*-
"""检查 Properties 页表单选中态：radio/checkbox、分类是否已选。"""
import sys
import time

sys.path.insert(0, r"C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts")
from cdp import CDPClient  # noqa: E402

CHECK_JS = r"""
(function () {
  var out = [];
  function walk(root, depth) {
    if (depth > 14) return;
    var nodes = root.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.shadowRoot) walk(el.shadowRoot, depth + 1);
      var tag = (el.tagName || '').toLowerCase();
      if (tag === 'input' && (el.type === 'radio' || el.type === 'checkbox')) {
        var lbl = '';
        try {
          var lab = el.closest('label');
          lbl = (lab && lab.innerText) || el.getAttribute('aria-label') || '';
        } catch (e) {}
        out.push({
          t: el.type,
          checked: !!el.checked,
          label: String(lbl).replace(/\s+/g, ' ').slice(0, 50)
        });
      }
    }
  }
  walk(document, 0);
  return JSON.stringify(out.slice(0, 30));
})()
"""


def main():
    c = CDPClient(host="127.0.0.1", port=9222, timeout=90)
    try:
        c.ensure_page(url_contains="/properties")
        c.send("Page.enable")
        c.send("Emulation.setDeviceMetricsOverride",
               {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1)
        c.screenshot(r"C:\Users\X\WorkBuddy\2026-09-20-11-24-33\edge-json-formatter"
                     r"\docs\shots\props-state.png")
        print("inputs:", c.evaluate(CHECK_JS).get("value"))
        txt = c.evaluate('document.body.innerText.replace(/\\s+/g, " ")').get("value") or ""
        # 找可能的错误提示
        for kw in ("required", "Required", "select a category", "error", "Error"):
            idx = txt.find(kw)
            if idx >= 0:
                print("err-hint:", txt[max(0, idx - 80):idx + 120])
                break
    finally:
        c.close()


if __name__ == "__main__":
    main()
