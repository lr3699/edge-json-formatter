#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-local.py —— 在真实 Edge + 已加载扩展的环境里做一次完整本地验收。

覆盖：
  1. 假 JSON 接口被自动接管（内容脚本注入 .jf-root 查看器）
  2. 「粘贴 JSON 格式化」编辑页可用
  3. 大 JSON（约 12MB）强制格式化不卡死、行数有上限
  4. 错误 JSON 给出行列定位
结果写 tools/_verify_local.txt。
"""

import json
import os
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path(
    os.environ.get("CDP_SKILL_SCRIPTS",
                   Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
sys.path.insert(0, str(SKILL_SCRIPTS))
from cdp import CDPClient, CDPError  # noqa: E402

ERROR_HOOK = """
window.__errs = [];
window.addEventListener('error', function (e) { window.__errs.push('error: ' + (e.message || e.type)); });
window.addEventListener('unhandledrejection', function (e) { window.__errs.push('rejection: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason))); });
"""


def ev(client, expr, timeout=120.0):
    res = client.send("Runtime.evaluate", {
        "expression": expr, "returnByValue": True, "awaitPromise": True, "userGesture": True,
    }, timeout=timeout)
    if res.get("exceptionDetails"):
        exc = res["exceptionDetails"]
        desc = (exc.get("exception") or {}).get("description") or exc.get("text")
        raise RuntimeError("页面 JS 异常：%s" % desc[:2000])
    return res.get("result", {}).get("value")


def find_extension_id(client):
    for t in client.targets():
        u = t.get("url") or ""
        if u.startswith("chrome-extension://") and u.endswith("/src/background/service-worker.js"):
            return u.split("/")[2]
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    client = CDPClient(host="127.0.0.1", port=9335, timeout=30.0)
    lines = []

    def log(s=""):
        lines.append(s)
        print(s)

    try:
        if not client.is_alive():
            log("CDP 无响应")
            return 2
        ext_id = find_extension_id(client)
        if not ext_id:
            log("找不到扩展 service worker")
            return 3
        log("扩展 ID: " + ext_id)

        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_HOOK})
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": 1440, "height": 940, "deviceScaleFactor": 1, "mobile": False})

        # ---------- 1) JSON 接口自动接管 ----------
        log("\n=== 1) JSON 接口自动接管 ===")
        client.navigate("http://127.0.0.1:18543/api/order", timeout=30.0)
        client.wait_for("document.readyState === 'complete'", timeout=15.0)
        time.sleep(1.5)
        r1 = json.loads(ev(client, """
        (function () {
          var v = document.querySelector('.jf-root');
          var rows = v ? v.querySelectorAll('.jf-row').length : 0;
          var keys = v ? v.querySelectorAll('.jf-key').length : 0;
          return JSON.stringify({
            takenOver: !!v, rows: rows, keys: keys,
            toolbar: !!v.querySelector('.jf-toolbar'),
            title: document.title,
            errors: window.__errs || []
          });
        })()
        """))
        log(json.dumps(r1, ensure_ascii=False, indent=2))
        client.screenshot(str(Path("docs") / "shots" / "local-takeover.png"))

        # ---------- 2) 编辑页 ----------
        log("\n=== 2) 粘贴 JSON 格式化编辑页 ===")
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30.0)
        client.wait_for("document.readyState === 'complete' && !!document.getElementById('input')",
                        timeout=15.0)
        time.sleep(0.8)
        r2 = json.loads(ev(client, """
        (async function () {
          var el = document.getElementById('input');
          var host = document.getElementById('viewer');
          el.value = '{"a":1,"b":[true,null,"x"],"c":{"d":600653836507516928}}';
          el.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }));
          await new Promise(function (r) { setTimeout(r, 900); });
          return JSON.stringify({
            rows: host.querySelectorAll('.jf-row').length,
            pill: document.getElementById('pillText').textContent,
            hasKey: !!host.querySelector('.jf-key'),
            errors: window.__errs || []
          });
        })()
        """))
        log(json.dumps(r2, ensure_ascii=False, indent=2))
        client.screenshot(str(Path("docs") / "shots" / "local-editor.png"))

        # ---------- 3) 大 JSON 不卡死 ----------
        log("\n=== 3) 大 JSON（12MB / 10 万项）===")
        r3 = json.loads(ev(client, """
        (async function () {
          var el = document.getElementById('input');
          var host = document.getElementById('viewer');
          var n = 100000;
          var parts = new Array(n);
          for (var i = 0; i < n; i++) {
            parts[i] = '{"id":' + i + ',"name":"项目-' + i + '","score":' + ((i * 7) % 100) + '.5,'
              + '"ok":' + (i % 2 === 0) + ',"tags":["a","b","c"]}';
          }
          var text = '[' + parts.join(',') + ']';
          var t0 = performance.now();
          el.value = text;
          el.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }));
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }));
          var rows = 0, t1 = null;
          for (var k = 0; k < 600; k++) {
            await new Promise(function (r) { setTimeout(r, 100); });
            rows = host.querySelectorAll('.jf-row').length;
            if (rows > 0) { t1 = performance.now(); break; }
          }
          var more = host.querySelector('.jf-summary');
          return JSON.stringify({
            inputChars: el.value.length,
            msToRows: t1 === null ? null : Math.round(t1 - t0),
            rows: rows,
            more: more ? more.textContent : null,
            pill: document.getElementById('pillText').textContent,
            errors: window.__errs || []
          });
        })()
        """, timeout=150.0))
        log(json.dumps(r3, ensure_ascii=False, indent=2))

        # ---------- 4) 错误 JSON 定位 ----------
        log("\n=== 4) 错误 JSON 行列定位 ===")
        r4 = json.loads(ev(client, """
        (async function () {
          var el = document.getElementById('input');
          el.value = '{\\n  "a": 1,\\n  "b": ,\\n  "c": 2\\n}';
          el.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }));
          await new Promise(function (r) { setTimeout(r, 700); });
          return JSON.stringify({
            pill: document.getElementById('pillText').textContent,
            msg: document.getElementById('msg').textContent,
            hasErrorCard: !!document.querySelector('.jf-error'),
            errors: window.__errs || []
          });
        })()
        """))
        log(json.dumps(r4, ensure_ascii=False, indent=2))

        # ---------- 结论 ----------
        problems = []
        if not r1.get("takenOver"):
            problems.append("JSON 接口未被接管")
        if r2.get("pill") != "格式化成功" and "成功" not in (r2.get("pill") or ""):
            problems.append("编辑页格式化未成功：%s" % r2.get("pill"))
        if r3.get("msToRows") is None:
            problems.append("大 JSON 渲染超时")
        elif r3.get("rows", 0) > 8000:
            problems.append("大 JSON 行数无上限：%d" % r3.get("rows"))
        if not r4.get("hasErrorCard"):
            problems.append("错误 JSON 未给出定位卡片")
        for key in ("r1", "r2", "r3", "r4"):
            if locals()[key].get("errors"):
                problems.append("%s 有 JS 报错" % key)

        log("\n" + ("=" * 40))
        if problems:
            log("[失败] %d 项：" % len(problems))
            for p in problems:
                log("  - " + p)
            return 6
        log("[通过] 本地验收全部符合预期")
        return 0
    except CDPError as exc:
        log("CDP 错误：" + str(exc))
        return 1
    finally:
        client.close()
        try:
            with open("tools/_verify_local.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
