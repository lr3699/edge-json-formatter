#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_shot-page.py —— 把任意本地 HTML 整页截成一张 PNG（无头 CDP）。

用法：
    python tools/_shot-page.py <html路径> <输出png> [--width 1000] [--port 9361]

用于「改前 / 改后」这类对照页的一次性存档出图；不参与正式构建。
"""
import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1000)
    ap.add_argument("--port", type=int, default=9361)
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=120.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": args.width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    c.send("Page.bringToFront")
    c.navigate(Path(args.html).resolve().as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=20)
    c.wait_for("document.fonts.status==='loaded'", timeout=15)
    c.send("Page.bringToFront")

    def height():
        raw = c.evaluate("Math.ceil(document.body.scrollHeight)", timeout=30)
        return raw.get("value") if isinstance(raw, dict) else raw

    h = height()
    res = c.send("Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": True, "fromSurface": True,
        "clip": {"x": 0, "y": 0, "width": args.width, "height": int(h), "scale": 1}})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(res["data"]))
    print("写入 %s（%dx%d，%d 字节）" % (out, args.width, int(h), out.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
