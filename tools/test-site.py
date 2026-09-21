#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-site.py —— 网页版（site/app.html）冒烟测试。

用 CDP 打开页面，灌入一段 JSON，检查：脚本无报错、树渲染成功、设置抽屉可用、
主题切换生效、分享链接可还原。

用法：
    python tools/test-site.py [--url http://127.0.0.1:18544/app.html] [--port 9222]
"""

import argparse
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient, CDPError  # noqa: E402

SAMPLE = '{"code":"0","msg":"success","data":{"orderId":"600653836507516928",' \
         '"amount":128.5,"paid":true,"tags":["vip","2026-09"],' \
         '"buyer":{"id":10086,"nickname":"\\u5f20\\u4e09"}}}'

ERR_COLLECTOR = (
    "window.__errs=[];"
    "window.addEventListener('error',function(e){window.__errs.push(String(e.message));});"
    "window.addEventListener('unhandledrejection',function(e){"
    "window.__errs.push('reject:'+String(e.reason));});"
)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18544/app.html")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--shot", help="额外截图保存路径")
    args = p.parse_args(argv)

    fails = []

    def check(name, cond, extra=""):
        mark = "PASS" if cond else "FAIL"
        if not cond:
            fails.append(name)
        print("  [%s] %-28s %s" % (mark, name, extra))

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=60)
    try:
        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.addScriptToEvaluateOnNewDocument", {"source": ERR_COLLECTOR})

        print("打开", args.url)
        ok = client.navigate(args.url, timeout=30)
        check("页面加载", ok)
        time.sleep(3.5)

        hooks = client.evaluate(
            "(function(){var N=window.__EDGE_JSON_FORMATTER__;"
            "return N ? JSON.stringify([typeof N.applyEditorSettings,"
            "typeof N.setEditorText,typeof N.createViewer,typeof N.loadSettings]) : 'NO_NS';})()"
        ).get("value")
        check("网页版钩子就绪", hooks and "NO_NS" not in hooks, str(hooks))

        import json as _json
        client.evaluate(
            "(function(){window.__EDGE_JSON_FORMATTER__.setEditorText(%s);})()"
            % _json.dumps(SAMPLE)
        )
        time.sleep(1.6)

        rows = client.evaluate("document.querySelectorAll('.jf-row').length").get("value")
        check("渲染出树", bool(rows) and rows > 3, "rows=%s" % rows)

        pill = client.evaluate("document.getElementById('pillText').textContent").get("value")
        check("状态为成功", pill and "成功" in pill, str(pill))

        shown = client.evaluate("!document.getElementById('viewer').hidden").get("value")
        check("输出面板可见", bool(shown))

        # 大整数精度
        big = client.evaluate(
            "(function(){var t=document.getElementById('viewer').innerText||'';"
            "return t.indexOf('600653836507516928')>=0;})()"
        ).get("value")
        check("大整数未丢精度", bool(big))

        # 设置抽屉
        client.evaluate("document.getElementById('btnOptions').click()")
        time.sleep(0.6)
        opened = client.evaluate("!document.getElementById('drawer').hidden").get("value")
        check("设置抽屉可打开", bool(opened))

        controls = client.evaluate("document.querySelectorAll('#drawerBody .set-row').length").get("value")
        check("设置项齐全", bool(controls) and controls >= 8, "rows=%s" % controls)

        # 切深色主题
        client.evaluate(
            "(function(){window.__EDGE_JSON_FORMATTER__.applyEditorSettings({theme:'dark'});})()"
        )
        time.sleep(0.5)
        dark = client.evaluate(
            "document.documentElement.getAttribute('data-theme')"
        ).get("value")
        check("深色主题生效", dark == "dark", str(dark))

        # 设置持久化
        saved = client.evaluate(
            "(function(){try{return JSON.parse(localStorage.getItem('jsonFormatterSettings')).theme;"
            "}catch(e){return null;}})()"
        ).get("value")
        check("设置写入 localStorage", saved == "dark", str(saved))

        client.evaluate("document.getElementById('drawerClose').click()")
        time.sleep(0.3)

        # 分享链接还原
        client.evaluate("document.getElementById('btnOptions').click()")
        time.sleep(0.4)
        client.evaluate("document.getElementById('btnShare').click()")
        time.sleep(0.6)
        hashed = client.evaluate("location.hash.slice(0, 12)").get("value")
        check("分享链接已生成", bool(hashed) and hashed.startswith("#j="), str(hashed))

        errs = client.evaluate("JSON.stringify(window.__errs||[])").get("value")
        errs = errs or "[]"
        check("无 JS 报错", errs == "[]", errs[:200])

        if args.shot:
            client.screenshot(args.shot)
            print("  截图:", args.shot)

        print("\n结果：%s" % ("全部通过" if not fails else "失败项 -> " + ", ".join(fails)))
        return 0 if not fails else 1
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
