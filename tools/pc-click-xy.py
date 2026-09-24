#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pc-click-xy.py —— 用 CDP 真实鼠标事件按视口坐标点击。

为什么要它：Partner Center 的 Confirm 模态框在异常重试后会出现**两个**
Confirm 候选（一个可见、一个残留隐藏），click-button.js 的
「最靠上、最靠右」策略会点到那个无效的。坐标点击绕开一切选择器歧义。

用法：python tools/pc-click-xy.py 557 595 [--port 9222]
"""
import argparse
import sys
from pathlib import Path

CDP_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(CDP_SCRIPTS))
from cdp import CDPClient  # noqa: E402


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("x", type=int)
    ap.add_argument("y", type=int)
    ap.add_argument("--port", type=int, default=9222)
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=60.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Page.bringToFront")
    for etype in ("mousePressed", "mouseReleased"):
        c.send("Input.dispatchMouseEvent", {
            "type": etype, "x": args.x, "y": args.y,
            "button": "left", "clickCount": 1,
        })
    print("已在 (%d, %d) 点击" % (args.x, args.y))
    return 0


if __name__ == "__main__":
    sys.exit(main())
