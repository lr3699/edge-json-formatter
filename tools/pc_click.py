#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pc_click.py —— 按「按钮文字」穿透 Shadow DOM 点击 Partner Center 里的按钮。

为什么不用 cdp.py 的 click：Partner Center 是 Web Components + Shadow DOM 的重 SPA，
普通 querySelector 根本找不到按钮；而且同名文字常同时出现在 div 容器上，
按 CSS 选容易点错节点（点 "Close" 时踩过这个坑）。

这里复用技能里的 click-button.js（只认 button / v6_he-button / [role=button]），
按文字精确匹配，多个候选取「最靠上、最靠右」的那个（工具条位置）。

用法：
    python tools/pc_click.py "Update" [--port 9222] [--dry]
    python tools/pc_click.py "Save & continue" --port 9222
"""

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(
    os.environ.get(
        "PC_SKILL_SCRIPTS",
        Path.home() / ".workbuddy" / "skills" / "partner-center-edge-submit" / "scripts",
    )
)
CDP_SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(CDP_SKILL_SCRIPTS))

try:
    from cdp import CDPClient, CDPError  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print("无法导入 cdp.py（来自 %s）：%s" % (CDP_SKILL_SCRIPTS, exc), file=sys.stderr)
    raise SystemExit(1)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(prog="pc_click.py")
    p.add_argument("text", help="按钮上的精确文字，如 Update / Publish")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--dry", action="store_true", help="只报告会点哪个，不真的点")
    args = p.parse_args(argv)

    click_js_path = SKILL_SCRIPTS / "click-button.js"
    if not click_js_path.exists():
        print("找不到 click-button.js：%s" % click_js_path, file=sys.stderr)
        return 1
    body = click_js_path.read_text(encoding="utf-8")

    if args.dry:
        body = body.replace("(inner || pick.el).click();", "/* dry-run */")

    # 把目标文字塞进 window 变量，再跑技能脚本
    expr = "window.__JF_CLICK_BTN = %s;\n%s" % (json.dumps(args.text), body)

    client = CDPClient(host=args.host, port=args.port, timeout=30.0)
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: %s 无响应" % client.base_http)
            return 2
        client.ensure_page()
        res = client.send("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        }, timeout=30.0)
        if res.get("exceptionDetails"):
            exc = res["exceptionDetails"]
            desc = (exc.get("exception") or {}).get("description") or exc.get("text")
            print("JS 异常：%s" % desc, file=sys.stderr)
            return 1
        val = res.get("result", {}).get("value")
        print(json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val)
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
            except Exception:
                return 0
            return 0 if parsed.get("ok") else 3
        return 0
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
