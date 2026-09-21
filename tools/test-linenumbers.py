#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-linenumbers.py —— 验证「显示行号」不再破坏缩进。

量法：找到深度不同的两个键行（code 与 orderId），对比它们 .jf-content 的
getBoundingClientRect().left —— 开行号后两者必须仍然拉开距离（嵌套缩进保留），
同时两个 .jf-no 行号的 left 应几乎相同（钉在同一列）。

用法：python tools/test-linenumbers.py [--url ...] [--port 9222] [--shot xxx.png]
"""

import argparse
import json
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient, CDPError  # noqa: E402

SAMPLE = json.dumps({
    "code": "0",
    "data": {"orderId": "600653836507516928", "buyer": {"id": 10086}},
}, ensure_ascii=False, indent=2)


def measure(client, label):
    expr = (
        "(function(){"
        "var rows=[].slice.call(document.querySelectorAll('.jf-row'));"
        "function find(txt){for(var i=0;i<rows.length;i++){"
        "var c=rows[i].querySelector('.jf-content');"
        "if(c&&c.textContent.indexOf(txt)===0)return rows[i];}return null;}"
        "var a=find('\"code\"'),b=find('\"orderId\"'),c2=find('\"id\"');"
        "function info(r){if(!r)return null;var no=r.querySelector('.jf-no');"
        "var ct=r.querySelector('.jf-content');"
        "return {no:no?Math.round(no.getBoundingClientRect().left):-1,"
        "ct:ct?Math.round(ct.getBoundingClientRect().left):-1,"
        "depth:r.style.getPropertyValue('--jf-depth')};}"
        "return JSON.stringify({code:info(a),orderId:info(b),id:info(c2)});})()"
    )
    val = client.evaluate(expr).get("value")
    print("  [%s] %s" % (label, val))
    return json.loads(val) if val else {}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18544/app.html")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--shot", help="截图保存路径")
    args = p.parse_args(argv)

    fails = []

    def check(name, cond, extra=""):
        if not cond:
            fails.append(name)
        print("  [%s] %-24s %s" % ("PASS" if cond else "FAIL", name, extra))

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=60)
    try:
        client.ensure_page()
        client.send("Page.enable")
        print("打开", args.url)
        client.navigate(args.url, timeout=30)
        time.sleep(3)

        client.evaluate(
            "(function(){window.__EDGE_JSON_FORMATTER__.setEditorText(%s);})()"
            % json.dumps(SAMPLE)
        )
        time.sleep(1.4)

        # 行号关闭（默认）：量基准缩进
        off = measure(client, "lineNumbers=OFF")
        base_gap = None
        if off.get("code") and off.get("orderId"):
            base_gap = off["orderId"]["ct"] - off["code"]["ct"]
            check("关行号时有缩进", base_gap >= 16, "orderId-code=%spx" % base_gap)

        # 打开行号
        client.evaluate(
            "(function(){window.__EDGE_JSON_FORMATTER__.applyEditorSettings({lineNumbers:true});})()"
        )
        time.sleep(1.2)
        on = measure(client, "lineNumbers=ON")

        if on.get("code") and on.get("orderId"):
            gap = on["orderId"]["ct"] - on["code"]["ct"]
            check("开行号后仍有缩进", gap >= 16, "orderId-code=%spx" % gap)
            if base_gap is not None:
                check("缩进与关行号时一致", abs(gap - base_gap) <= 2,
                      "off=%s on=%s" % (base_gap, gap))
            nos = [on[k]["no"] for k in ("code", "orderId", "id") if on.get(k)]
            check("行号钉在同一列", len(nos) == 3 and max(nos) - min(nos) <= 2, str(nos))
        else:
            check("拿到测量行", False)

        if args.shot:
            client.screenshot(args.shot)
            print("  截图:", args.shot)

        print("\n结果：%s" % ("全部通过" if not fails else "失败 -> " + ", ".join(fails)))
        return 0 if not fails else 1
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
