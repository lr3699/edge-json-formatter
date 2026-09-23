#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成站点社交分享卡 site/og-image.png（1200×630）。

来源页面 docs/icon-redesign/og-image.html 随图保留，改版式改那一个文件即可。
图标取自 icons/icon128.png（与扩展同一套），避免品牌不一致。

用法：python tools/make-og-image.py --port 9341
"""
import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

W, H = 1200, 630


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9341)
    args = ap.parse_args()

    src = ROOT / "docs" / "icon-redesign" / "og-image.html"
    if not src.exists():
        print("缺少来源页面 %s" % src, file=sys.stderr)
        return 1

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    c.ensure_page()
    # 锁定设备缩放为 1：本机显示缩放 125% 会把 1200×630 截成 1500×788
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
    c.send("Page.bringToFront")
    c.navigate(src.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=20)
    c.send("Page.bringToFront")

    res = c.send("Page.captureScreenshot", {
        "format": "png",
        "clip": {"x": 0, "y": 0, "width": W, "height": H, "scale": 1},
    })
    out = ROOT / "site" / "og-image.png"
    out.write_bytes(base64.b64decode(res["data"]))
    print("写入 %s（%d 字节）" % (out.relative_to(ROOT), out.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
