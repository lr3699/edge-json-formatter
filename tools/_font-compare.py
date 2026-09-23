#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时：同版式换字体渲染图标做对比（黑底 + 角括号 + JSON）。用完即删。"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VB, RADIUS = 512, 112
BG_TOP, BG_BOTTOM, FG = "#1C1C1F", "#050506", "#FFFFFF"
BR_W, BR_X, BR_ARM, BR_Y0, BR_Y1 = 20, 48, 52, 196, 318
FILL = 0.62
PROBE_FS = 100

# (标签, font-family, 字重)
CANDS = [
    ("Segoe UI Black（当前）", "'Segoe UI Black'", 900),
    ("Arial Black", "'Arial Black'", 900),
    ("Bahnschrift SemiBold", "Bahnschrift", 600),
    ("Bahnschrift Bold", "Bahnschrift", 700),
    ("Impact", "Impact", 400),
    ("Verdana Bold", "Verdana", 700),
    ("Tahoma Bold", "Tahoma", 700),
    ("Trebuchet MS Bold", "'Trebuchet MS'", 700),
]


def corner(right):
    def X(v):
        return VB - v if right else v
    y_arm, y_end = (BR_Y1, BR_Y0) if right else (BR_Y0, BR_Y1)
    return "M %.0f %.0f L %.0f %.0f L %.0f %.0f" % (X(BR_X + BR_ARM), y_arm, X(BR_X), y_arm, X(BR_X), y_end)


def body(font, fs, baseline):
    return (
        '<rect width="%(vb)d" height="%(vb)d" rx="%(r)d" fill="url(#bg)"/>'
        '<text x="%(cx).1f" y="%(by).1f" text-anchor="middle" '
        'style="font-family:%(font)s;font-weight:%(fw)d;font-size:%(fs).2fpx;fill:%(fg)s">'
        'JSON</text>'
        '<g fill="none" stroke="%(fg)s" stroke-width="%(bw)d" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="%(bl)s"/><path d="%(br)s"/></g>'
        % {"vb": VB, "r": RADIUS, "cx": VB / 2, "by": baseline, "font": font, "fw": 0,
           "fs": fs, "fg": FG, "bw": BR_W, "bl": corner(False), "br": corner(True)})


def svg(font, weight, fs, baseline):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">'
            '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/>'
            '</linearGradient></defs>%s</svg>'
            % (VB, VB, BG_TOP, BG_BOTTOM,
               body(font, fs, baseline).replace("font-weight:0", "font-weight:%d" % weight)))


def ev(c, js):
    raw = c.evaluate(js, timeout=60)
    if isinstance(raw, dict):
        raw = raw.get("value", raw)
    return raw


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9341
    c = CDPClient(host="127.0.0.1", port=port, timeout=300.0)
    c.ensure_page()
    c.send("Page.bringToFront")

    cells = []
    for label, font, weight in CANDS:
        tmp = ROOT / "dist" / "_fc.html"
        tmp.write_text("<!DOCTYPE html><html><body></body></html>", encoding="utf-8")
        c.navigate(tmp.as_uri(), timeout=30.0)
        js = ("(function(){var cv=document.createElement('canvas');var x=cv.getContext('2d');"
              "x.font='%d %dpx '+%s;var m=x.measureText('JSON');"
              "return JSON.stringify({w:m.width,a:m.actualBoundingBoxAscent,"
              "d:m.actualBoundingBoxDescent});})()" % (weight, PROBE_FS, json.dumps(font)))
        mt = json.loads(ev(c, js))
        fs = (VB * FILL) / (mt["w"] / PROBE_FS)
        top = mt["a"] / PROBE_FS * fs
        bot = mt["d"] / PROBE_FS * fs
        baseline = (VB - (top + bot)) / 2.0 + top
        cells.append((label, svg(font, weight, fs, baseline), fs, top + bot))

    html = ['<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            'body{background:#0d0f13;color:#e5e7eb;font-family:"Segoe UI",sans-serif;margin:24px}'
            '.grid{display:flex;flex-wrap:wrap;gap:26px}'
            '.cell{width:300px}.lbl{font-size:12px;color:#9ca3af;margin:8px 0 0}'
            '.metric{font-size:11px;color:#6b7280}</style></head><body><div class="grid">']
    for label, code, fs, ink in cells:
        html.append('<div class="cell">%s<div class="lbl">%s</div>'
                    '<div class="metric">字号 %.0f · 字高 %.0f（%.0f%% 版面）</div></div>'
                    % (code.replace("<svg ", '<svg width="280" height="280" ', 1),
                       label, fs, ink, 100 * ink / VB))
    html.append("</div></body></html>")
    p = ROOT / "dist" / "_font-compare.html"
    p.write_text("".join(html), encoding="utf-8")
    c.navigate(p.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    c.send("Page.bringToFront")
    res = c.send("Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": True,
        "clip": {"x": 0, "y": 0, "width": 700, "height": 1300, "scale": 1}})
    out = ROOT / "dist" / "_font-compare.png"
    out.write_bytes(base64.b64decode(res["data"]))
    print("已保存", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
