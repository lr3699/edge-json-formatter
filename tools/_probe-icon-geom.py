#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_probe-icon-geom.py —— 排查「图标圆角外有白边」的几何探针。

背景：Page.captureScreenshot 把页面合成到不透明白底上（colorType=2，无 alpha），
圆角外就成了纯白 —— 深色工具栏里看到一圈白边。
本探针回答两件事：
  1. 每个尺寸的 <svg> / 内部 <rect> 在页面里的真实 boundingClientRect（是否偏移/被裁）；
  2. 透明底 + `svg{display:block}` 之后，抓出来的 PNG 四角是否真的 alpha=0。
"""
import base64
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient          # noqa: E402
from png_read import read_png      # noqa: E402

_spec = importlib.util.spec_from_file_location("mk", ROOT / "tools" / "make-icons.py")
mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mk)

DUMP = """
(function(){
  var out=[];
  document.querySelectorAll('body > div').forEach(function(d, i){
    var svg = d.querySelector('svg'), rc = d.querySelector('rect');
    function r(e){ if(!e) return null; var b=e.getBoundingClientRect();
      return [+b.x.toFixed(2), +b.y.toFixed(2), +b.width.toFixed(2), +b.height.toFixed(2)]; }
    out.push({i:i, left:d.style.left, cssH:d.style.height, div:r(d), svg:r(svg), rect:r(rc)});
  });
  return JSON.stringify(out);
})()
"""


def dump(c, tag):
    raw = c.evaluate(DUMP, timeout=30)
    if isinstance(raw, dict):
        raw = raw.get("value", raw)
    print("--- %s ---" % tag)
    for row in json.loads(raw):
        print("  left=%-5s div=%-26s svg=%-26s rect=%s"
              % (row["left"], row["div"], row["svg"], row["rect"]))


def grid(path, n, label):
    im = read_png(str(path))
    step = max(1, n // 16)
    print("--- %s（alpha 采样，每 %d 像素）---" % (label, step))
    for y in range(0, n, step):
        print("  y=%3d " % y + "".join("%5d" % im.px(x, y)[3] for x in range(0, n, step)))
    print("  四角 RGB+alpha：%s %s %s %s" % (im.px(0, 0), im.px(n - 1, 0),
                                            im.px(0, n - 1), im.px(n - 1, n - 1)))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9349
    c = CDPClient(host="127.0.0.1", port=port, timeout=300.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1400, "height": 800, "deviceScaleFactor": 1, "mobile": False})
    c.send("Emulation.setDefaultBackgroundColorOverride",
           {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
    c.send("Page.bringToFront")

    M = mk.measure(c)
    sizes = [16, 32, 48]
    entries = [("s%d" % s, s, mk.svg(mk.marks_for(s, M))) for s in sizes]
    html, xs = mk.page_with(entries)
    tmp = ROOT / "dist" / "_icon-probe-geom.html"
    tmp.write_text(html, encoding="utf-8")
    c.navigate(tmp.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)

    dump(c, "现状（SVG 为 inline 元素）")
    # 实验：把 SVG 变成 block，消除行内基线对齐带来的位移
    c.evaluate("(function(){var s=document.createElement('style');"
               "s.textContent='svg{display:block}';document.head.appendChild(s);return 1})()",
               timeout=15)
    dump(c, "加 svg{display:block} 之后")

    for s in sizes:
        res = c.send("Page.captureScreenshot", {
            "format": "png",
            "clip": {"x": xs["s%d" % s], "y": 0, "width": s, "height": s, "scale": 1}})
        out = ROOT / "dist" / ("_probe-icon%d.png" % s)
        out.write_bytes(base64.b64decode(res["data"]))
        grid(out, s, "%dpx（透明底 + display:block）" % s)
    tmp.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
