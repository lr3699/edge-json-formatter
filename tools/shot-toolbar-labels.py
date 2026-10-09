#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shot-toolbar-labels.py —— 复查「文字标签工具栏 + 悬停补充说明」改版。

用法：
    python tools/shot-toolbar-labels.py

产出（docs/toolbar-labels/）：
    light-1440.png        亮色 · 默认分栏
    dark-1440.png         暗色 · 默认分栏
    narrow-900.png        900 视口
    tight-1000-split20.png 1000 视口 + 分栏 20%（按钮最挤的极限情况）
    hover-zoom-*.png      悬停某一枚按钮时标题行的 3 倍放大图（看提示气泡）
    metrics.json          顶栏 / 标题行 / 状态带 / 输入区 的实测高度

同时打印一份高度对照，便于确认「JSON 区域确实变大了」。
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path(
    os.environ.get(
        "CDP_SKILL_SCRIPTS",
        Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts",
    )
)
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient  # noqa: E402

OUT = Path("docs/toolbar-labels")
PAGE = Path("site/app.html").resolve().as_uri()

METRICS = r"""
(function () {
  var g = function (sel) {
    var n = document.querySelector(sel);
    if (!n) return null;
    var r = n.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  };
  var tools = document.querySelector('.panel-tools');
  var btns = tools ? tools.querySelectorAll('.btn') : [];
  var rowTop = null, rows = 0;
  for (var i = 0; i < btns.length; i++) {
    var t = Math.round(btns[i].getBoundingClientRect().top);
    if (rowTop === null) { rowTop = t; }
    else if (Math.abs(t - rowTop) > 2) { rows = 1; }
  }
  var tips = document.querySelectorAll('.btn-tip');
  var tipVisible = 0;
  for (var j = 0; j < tips.length; j++) {
    if (getComputedStyle(tips[j]).visibility !== 'hidden') tipVisible++;
  }
  return JSON.stringify({
    topbar: g('.topbar'),
    brand: g('.brand-mark'),
    panelHead: g('.panel-head'),
    panelFoot: g('.panel-foot'),
    inputPanel: g('#panelInput'),
    editorWrap: g('.editor-wrap'),
    panelTitleVisible: !!document.querySelector('.panel-title') &&
                       getComputedStyle(document.querySelector('.panel-title')).display !== 'none',
    btnCount: btns.length,
    toolbarRows: rows + 1,
    toolbar: g('.panel-tools'),
    tipVisible: tipVisible,
    tipTotal: tips.length,
    topbarBtnH: g('.topbar-tools .btn')
  });
})()
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    OUT.mkdir(parents=True, exist_ok=True)

    c = CDPClient(host="127.0.0.1", port=9222, timeout=120)
    c.ensure_page()
    c.send("Page.enable")
    c.send("Network.enable")
    c.send("Network.setCacheDisabled", {"cacheDisabled": True})

    def ev(expr, timeout=60):
        """cdp.evaluate 返回的是 Runtime.evaluate 的 result 包装，这里取 value。"""
        r = c.evaluate(expr, timeout=timeout)
        if isinstance(r, dict) and "value" in r:
            return r["value"]
        return r

    def evj(expr):
        """求值一段返回 JSON 字符串的表达式。"""
        v = ev(expr)
        if isinstance(v, (dict, list)):
            return v
        return json.loads(v)

    def shot(path, w, h, clip=None, scale=1.0, settle=0.5):
        c.send("Emulation.setDeviceMetricsOverride",
               {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(settle)
        params = {"format": "png"}
        if clip:
            params["clip"] = {"x": clip[0], "y": clip[1],
                              "width": clip[2], "height": clip[3], "scale": scale}
        res = c.send("Page.captureScreenshot", params, timeout=90)
        Path(path).write_bytes(base64.b64decode(res["data"]))
        print("  ->", path)

    def load(theme):
        c.send("Emulation.setEmulatedMedia",
               {"features": [{"name": "prefers-color-scheme", "value": theme}]})
        c.navigate(PAGE, timeout=90)
        c.wait_for("document.readyState==='complete'", timeout=60)
        time.sleep(2.0)
        # 载入示例数据，让两栏都有内容可看
        ev("(document.getElementById('btnSample')||{click:function(){}}).click()", timeout=30)
        time.sleep(1.2)

    def hover(sel):
        box = ev(
            "(function(){var n=document.querySelector(%s);if(!n)return '';"
            "var r=n.getBoundingClientRect();"
            "return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2});})()" % json.dumps(sel),
            timeout=30)
        if not box:
            return None
        p = box if isinstance(box, dict) else json.loads(box)
        c.send("Input.dispatchMouseEvent",
               {"type": "mouseMoved", "x": p["x"], "y": p["y"], "buttons": 0})
        time.sleep(0.5)
        return p

    def unhover():
        c.send("Input.dispatchMouseEvent",
               {"type": "mouseMoved", "x": 5, "y": 700, "buttons": 0})
        time.sleep(0.4)

    # ---------- 亮色 1440 ----------
    print("亮色 1440")
    load("light")
    ev("document.documentElement.style.setProperty('--split','36%');1")
    time.sleep(0.4)
    shot(OUT / "light-1440.png", 1440, 900)
    metrics = evj(METRICS)

    # 悬停「转义」按钮 → 标题行放大
    hover("#btnEscape")
    m2 = evj(METRICS)
    metrics["hover_tipVisible"] = m2["tipVisible"]
    shot(OUT / "hover-zoom-btnEscape.png", 1440, 900,
         clip=(0, 0, 720, 110), scale=2.2, settle=0.4)
    hover("#btnFromUni")
    shot(OUT / "hover-zoom-btnFromUni.png", 1440, 900,
         clip=(0, 0, 720, 110), scale=2.2, settle=0.4)
    unhover()

    # ---------- 暗色 1440 ----------
    print("暗色 1440")
    load("dark")
    time.sleep(0.6)
    shot(OUT / "dark-1440.png", 1440, 900)
    metrics["dark"] = evj(METRICS)

    # ---------- 窄视口 900 ----------
    print("窄视口 900")
    load("light")
    ev("document.documentElement.style.setProperty('--split','36%');1")
    shot(OUT / "narrow-900.png", 900, 760)
    metrics["narrow900"] = evj(METRICS)

    # ---------- 最挤：1000 视口 + 分栏 20% ----------
    print("1000 / split 20%")
    load("light")
    ev("document.documentElement.style.setProperty('--split','20%');1")
    time.sleep(0.4)
    shot(OUT / "tight-1000-split20.png", 1000, 760)
    metrics["tight"] = evj(METRICS)

    (OUT / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n实测高度（1440 亮色）：")
    for k in ("topbar", "brand", "panelHead", "panelFoot", "inputPanel", "editorWrap",
              "toolbar", "topbarBtnH"):
        v = metrics.get(k)
        print("  %-12s %s" % (k, ("%sx%s" % (v["w"], v["h"])) if v else "—"))
    print("  工具栏按钮数        %s" % metrics["btnCount"])
    print("  工具栏行数          %s" % metrics["toolbarRows"])
    print("  标题可见            %s" % metrics["panelTitleVisible"])
    print("  静止时可见提示数    %s/%s" % (metrics["tipVisible"], metrics["tipTotal"]))
    print("  悬停后可见提示数    %s" % metrics.get("hover_tipVisible"))
    print("\nOK ->", OUT.resolve())


if __name__ == "__main__":
    main()
