#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成字号调整前后的对比页（自包含 HTML，图片以 base64 内嵌，不依赖外部文件）。

为什么要这个脚本：本机没装 Pillow，无法裁剪/拼接 PNG。
改用 CSS 的 background-position + background-size 做等比放大裁切，
既不用图像库，也能把两版的正文字体放在同一视觉尺度下对比。

用法：
    python tools/make_font_compare.py
产出：
    docs/font-compare.html
"""

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# 裁切区域（原始 1280x800 截图坐标）与放大倍数
CROP_X, CROP_Y, CROP_W, CROP_H = 0, 40, 440, 250
ZOOM = 1.6

PANELS = [
    {
        "title": "调整前",
        "sub": "13.5px · font-weight 400 · 抗锯齿平滑（偏细）",
        "file": "verify-local-ext.png",
        "accent": "#c0392b",
    },
    {
        "title": "调整后",
        "sub": "15px · font-weight 500 · 关闭抗锯齿薄化 · Cascadia Mono/Consolas 优先",
        "file": "verify-font-after.png",
        "accent": "#2f9e3d",
    },
]


def to_data_uri(path: Path, mime: str = "image/png") -> str:
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def main() -> int:
    panels_html = []
    for p in PANELS:
        fp = DOCS / p["file"]
        if not fp.exists():
            print("缺少截图：%s" % fp, file=sys.stderr)
            return 1
        uri = to_data_uri(fp)
        panels_html.append(
            '<section class="panel">'
            '<header><span class="dot" style="background:%s"></span>'
            '<b>%s</b><em>%s</em></header>'
            '<div class="shot" style="background-image:url(\'%s\')"></div>'
            '</section>' % (p["accent"], p["title"], p["sub"], uri)
        )

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>字号调整前后对比</title>
<style>
  :root {{
    --crop-x: {cx}px; --crop-y: {cy}px;
    --vw: {vw}px;    /* 裁切区放大后的显示宽度 */
    --vh: {vh}px;
    --bg-w: {bgw}px; /* 原图放大后的尺寸，作为 background-size */
    --bg-h: {bgh}px;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 28px;
    background: #f5f6f8; color: #1f2328;
    font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  }}
  h1 {{ margin: 0 0 4px; font-size: 20px; }}
  .lead {{ margin: 0 0 22px; color: #6b7280; font-size: 13px; }}
  .panel {{
    background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 14px 16px 18px; margin-bottom: 18px; max-width: 720px;
    box-shadow: 0 1px 2px rgba(16,24,40,.05);
  }}
  .panel header {{
    display: flex; align-items: center; gap: 9px; flex-wrap: wrap;
    margin-bottom: 12px; font-size: 13.5px;
  }}
  .panel header b {{ font-size: 14.5px; }}
  .panel header em {{ color: #6b7280; font-style: normal; font-size: 12.5px; }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }}
  .shot {{
    width: var(--vw); height: var(--vh);
    border: 1px solid #eceef1; border-radius: 8px;
    background-repeat: no-repeat;
    background-size: var(--bg-w) var(--bg-h);
    background-position: calc(var(--crop-x) * -1) calc(var(--crop-y) * -1);
    max-width: 100%;
  }}
  footer {{ color: #6b7280; font-size: 12.5px; max-width: 720px; line-height: 1.7; }}
  footer code {{ background: #eceef1; padding: 1px 5px; border-radius: 4px; }}
</style>
</head>
<body>
  <h1>查看器正文字体：调整前后对比</h1>
  <p class="lead">同一台机器、同一张假接口页面（<code>http://127.0.0.1:18543/api/order</code>）、
     同样的 1280×800 视口，截取左上角 JSON 正文区域放大 {zoom}× 显示。</p>
  {panels}
  <footer>
    改动点：默认字号 <code>13 → 15px</code>；正文 <code>font-weight 400 → 500</code>；
    去掉 <code>-webkit-font-smoothing:antialiased</code>（它在 Windows 上会把笔画渲染得更细）；
    字体栈把 <code>Cascadia Mono / Consolas</code> 提到 <code>ui-monospace</code> 之前。
  </footer>
</body>
</html>
""".format(
        cx=CROP_X, cy=CROP_Y,
        vw=int(CROP_W * ZOOM), vh=int(CROP_H * ZOOM),
        bgw=int(1280 * ZOOM), bgh=int(800 * ZOOM),
        zoom=ZOOM,
        panels="\n  ".join(panels_html),
    )

    out = DOCS / "font-compare.html"
    out.write_text(html, encoding="utf-8")
    print("已生成：%s  (%.0f KB)" % (out, out.stat().st_size / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
