#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shoot_promo.py —— 把 docs/promo-tiles.html 里的三块推广图按精确尺寸截图。

Chrome 网上应用店要求的推广图尺寸：
    小推广图   440 x 280
    大推广图   920 x 680
    横幅推广图 1400 x 560

用法：
    python tools/shoot_promo.py [--port 9222]
产物写到 docs/chrome-assets/ 下。
"""

import argparse
import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient, CDPError  # noqa: E402

JOBS = [
    ("t-small", "promo-small-440x280.png", 440, 280),
    ("t-large", "promo-large-920x680.png", 920, 680),
    ("t-marquee", "promo-marquee-1400x560.png", 1400, 560),
]


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args(argv)

    html = ROOT / "docs" / "promo-tiles.html"
    if not html.exists():
        print("找不到 %s" % html)
        return 1
    outdir = ROOT / "docs" / "chrome-assets"
    outdir.mkdir(parents=True, exist_ok=True)

    url = html.as_uri()
    client = CDPClient(host=args.host, port=args.port, timeout=60)
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: 9222 无响应，请先启动调试浏览器")
            return 2
        client.ensure_page()
        client.send("Page.enable")
        client.send("Emulation.setDeviceMetricsOverride", {
            "width": 1500, "height": 1000, "deviceScaleFactor": 1, "mobile": False,
        })
        ok = client.navigate(url, timeout=30)
        print("navigate:", ok)
        time.sleep(2.0)

        for el_id, name, w, h in JOBS:
            rect = client.evaluate(
                "(function(){var e=document.getElementById(%s);"
                "if(!e) return null; var r=e.getBoundingClientRect();"
                "return JSON.stringify({x:r.x+scrollX,y:r.y+scrollY,w:r.width,h:r.height});})()"
                % '"%s"' % el_id
            ).get("value")
            if not rect:
                print("跳过 %s：页面里找不到该元素" % el_id)
                continue
            import json
            r = json.loads(rect)
            clip = {
                "x": r["x"], "y": r["y"],
                "width": int(r["w"]), "height": int(r["h"]),
                "scale": 1,
            }
            res = client.send("Page.captureScreenshot", {
                "format": "png", "clip": clip, "captureBeyondViewport": True,
            }, timeout=60)
            data = res.get("data")
            if not data:
                print("截图失败：%s" % el_id)
                continue
            out = outdir / name
            out.write_bytes(base64.b64decode(data))
            print("%-30s %s  (%dx%d)" % (name, out.stat().st_size, w, h))
        return 0
    except CDPError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
