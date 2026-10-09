#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
toolbar-preview.py —— 给「输入栏工具栏」出对照图。

用法：
    python tools/toolbar-preview.py --url http://127.0.0.1:8123/app.html

产出（默认写到 docs/toolbar-v2/）：
    light-1440.png    亮色 · 默认分栏
    dark-1440.png     暗色 · 默认分栏
    narrow-900.png    窄视口 + 最窄分栏（看整组换行）
    zoom-light.png    三态工具栏区域放大对照（便于逐像素看按钮边界）

为什么单独一支：工具栏宽度/分组是这次改版的核心，必须能一眼比对
「默认宽度 / 窄宽度 / 明暗主题」三种状态，而不是只截一张。
"""

import argparse
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

OUT_DEFAULT = "docs/toolbar-v2"


def shot(client, path, width, height, full=False):
    client.send("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
    })
    time.sleep(0.45)
    params = {"format": "png", "captureBeyondViewport": full}
    res = client.send("Page.captureScreenshot", params, timeout=60)
    import base64
    Path(path).write_bytes(base64.b64decode(res["data"]))
    return path


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="toolbar-preview.py")
    ap.add_argument("--url", default="http://127.0.0.1:8123/app.html")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--port", type=int, default=9222)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=120)
    c.ensure_page()
    c.send("Page.enable")
    c.send("Network.enable")
    c.send("Network.setCacheDisabled", {"cacheDisabled": True})

    def ev(expr):
        r = c.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
            "awaitPromise": True, "userGesture": True,
        }, timeout=60)
        return r.get("result", {}).get("value")

    def load(theme_media=None):
        c.send("Emulation.setEmulatedMedia",
               {"features": [{"name": "prefers-color-scheme",
                              "value": theme_media or "light"}]})
        c.navigate(args.url, timeout=90)
        c.wait_for("document.readyState==='complete'", timeout=60)
        time.sleep(2.2)

    # ---- 亮色 · 1440 ----
    load("light")
    ev("document.documentElement.style.setProperty('--split','36%');1")
    time.sleep(0.4)
    shot(c, out / "light-1440.png", 1440, 900)

    # ---- 暗色 · 1440 ----
    load("dark")
    time.sleep(0.8)
    shot(c, out / "dark-1440.png", 1440, 900)

    # ---- 窄视口 + 最窄分栏（整组换行）----
    load("light")
    ev("document.documentElement.style.setProperty('--split','20%');1")
    time.sleep(0.4)
    shot(c, out / "narrow-900.png", 900, 760)

    # ---- 局部放大对照 ----
    from PIL import Image, ImageDraw

    tiles = []
    for name, label in [("light-1440.png", "亮色 · 1440（默认分栏 36%）"),
                        ("dark-1440.png", "暗色 · 1440"),
                        ("narrow-900.png", "窄视口 900 · 分栏 20%（整组换行）")]:
        im = Image.open(out / name).convert("RGB")
        # 输入面板标题栏：从面板左边缘到面板右边缘，纵向取标题行
        # app.html 里 .workspace padding 16px，分栏宽度由 --split 决定
        tiles.append((label, im))

    Z = 2  # 放大倍数
    PAD = 24
    rows = []
    for label, im in tiles:
        # 裁出整条标题行（x: 0..面板宽, y: 约 56..104）
        crop = im.crop((0, 52, min(im.width, 760), 106))
        crop = crop.resize((crop.width * Z, crop.height * Z), Image.LANCZOS)
        rows.append((label, crop))

    W = max(r[1].width for r in rows) + PAD * 2
    H = PAD + sum(r[1].height + 40 for r in rows) + PAD
    sheet = Image.new("RGB", (W, H), (246, 247, 249))
    dr = ImageDraw.Draw(sheet)
    y = PAD
    for label, im in rows:
        dr.text((PAD, y), label, fill=(40, 46, 56))
        y += 22
        sheet.paste(im, (PAD, y))
        y += im.height + 18
    sheet.save(out / "zoom-light.png")

    print("OK ->", out.resolve())
    for f in sorted(out.glob("*.png")):
        from PIL import Image as I
        print("   %-18s %s" % (f.name, I.open(f).size))


if __name__ == "__main__":
    main()
