#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdp_viewport.py —— 调整 CDP 页面视口尺寸后截图。

为什么需要：默认浏览器窗口可能只有 ~880px 宽，Partner Center 这类 SPA 的
顶栏 / 侧栏会被裁掉，截图里看不到关键按钮（比如账户设置齿轮）。
放大视口后再截图，能一次看全。

用法：
    python tools/cdp_viewport.py 1440 1000 docs/shot.png [--full] [--port 9222]
"""

import argparse
import os
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(
    os.environ.get(
        "CDP_SKILL_SCRIPTS",
        Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts",
    )
)
sys.path.insert(0, str(SKILL_SCRIPTS))

try:
    from cdp import CDPClient, CDPError  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print("无法导入 cdp.py（来自 %s）：%s" % (SKILL_SCRIPTS, exc), file=sys.stderr)
    raise SystemExit(1)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(prog="cdp_viewport.py", description="设置视口后截图")
    p.add_argument("width", type=int, nargs="?", default=1440)
    p.add_argument("height", type=int, nargs="?", default=1000)
    p.add_argument("output", nargs="?", default="docs/shot.png")
    p.add_argument("--full", action="store_true", help="截整页")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--target")
    p.add_argument("--url-contains")
    args = p.parse_args(argv)

    client = CDPClient(host=args.host, port=args.port, timeout=30.0)
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: %s 无响应" % client.base_http)
            return 2
        client.ensure_page(target=args.target, url_contains=args.url_contains)

        client.send("Emulation.setDeviceMetricsOverride", {
            "width": args.width,
            "height": args.height,
            "deviceScaleFactor": 1,
            "mobile": False,
        })
        path = client.screenshot(args.output, full_page=args.full)
        print("视口 %dx%d，截图已保存：%s" % (args.width, args.height, path))
        return 0
    except CDPError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
