#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdp_js.py —— 在当前页面上下文里执行 JS，并等待 Promise 结果（awaitPromise）。

cdp.py 的 eval 不带 awaitPromise，所以任何 async/await、fetch(...) 都拿不到结果。
本脚本补上这一点：在页面里以「同源 + 带 Cookie」的方式发请求，直接读接口返回，
用来判断登录态 / 账号状态，比在 UI 上瞎点可靠得多。

用法：
    python tools/cdp_js.py --file script.js [--port 9222]
    python tools/cdp_js.py "fetch('/api/x').then(r=>r.text())"

JS 文件里应 `return` 或直接以表达式结尾；推荐写成 async IIFE 返回 JSON 字符串：
    (async function(){ const r = await fetch('/api/x', {credentials:'include'});
      return JSON.stringify({status:r.status, body:(await r.text()).slice(0,2000)}); })()
"""

import argparse
import json
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
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(prog="cdp_js.py", description="带 awaitPromise 的 CDP JS 执行器")
    p.add_argument("expression", nargs="?", help="JS 表达式")
    p.add_argument("--file", help="从文件读取 JS")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--target", help="指定标签页 targetId")
    p.add_argument("--url-contains", help="按 URL 关键字挑选标签页")
    p.add_argument("--timeout", type=float, default=45.0)
    args = p.parse_args(argv)

    if args.file:
        fp = Path(args.file)
        if not fp.exists():
            print("错误：JS 文件不存在：%s" % fp, file=sys.stderr)
            return 1
        expr = fp.read_text(encoding="utf-8")
    else:
        expr = args.expression

    if not expr:
        print("错误：需要给出 JS 表达式或 --file。", file=sys.stderr)
        return 1

    client = CDPClient(host=args.host, port=args.port, timeout=args.timeout)
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: %s 无响应" % client.base_http)
            return 2
        client.ensure_page(target=args.target, url_contains=args.url_contains)

        res = client.send("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,      # ← 关键：等 Promise 落地
            "userGesture": True,
        }, timeout=args.timeout)

        if res.get("exceptionDetails"):
            exc = res["exceptionDetails"]
            desc = (exc.get("exception") or {}).get("description") or exc.get("text")
            print("JS 执行异常：%s" % desc, file=sys.stderr)
            return 1

        val = res.get("result", {}).get("value")
        if isinstance(val, (dict, list)):
            print(json.dumps(val, ensure_ascii=False, indent=2))
        else:
            print(val if val is not None else "")
        return 0
    except CDPError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
