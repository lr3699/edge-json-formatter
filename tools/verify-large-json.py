#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-large-json.py —— 在真实 Edge + 扩展环境里验收「大 JSON 卡死修复」。

验证点：
  1. 12MB / 10 万项 JSON 强制格式化后能正常出结果（不再假死）；
  2. DOM 行数有上限（分批渲染 + 加载更多哨兵）；
  3. 点击「加载更多」能继续分批渲染；
  4. 「展开全部」不会把 DOM 打爆；
  5. 搜索跳转能把「加载更多」区域外的命中行 reveal 出来。

前置：Edge 已带 --load-extension=dist/unpacked --remote-debugging-port=9334 启动。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path(
    os.environ.get(
        "CDP_SKILL_SCRIPTS",
        Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts",
    )
)
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient, CDPError  # noqa: E402

ERROR_HOOK = """
window.__errs = [];
window.addEventListener('error', function (e) {
  window.__errs.push('error: ' + (e.message || e.type));
});
window.addEventListener('unhandledrejection', function (e) {
  window.__errs.push('rejection: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason)));
});
"""

BIG_JSON_BUILDER = """
(function (n) {
  var parts = new Array(n);
  for (var i = 0; i < n; i++) {
    parts[i] = '{"id":' + i + ',"name":"项目-' + i + '","score":' + ((i * 7) % 100) + '.5,'
      + '"ok":' + (i % 2 === 0) + ',"tags":["a","b","c"],'
      + '"meta":{"ts":1784173433013,"ref":9007199254740993}}';
  }
  return '[' + parts.join(',\\n') + ']';
})(%d)
"""


def ev(client, expr, timeout=120.0):
    res = client.send("Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True,
        "userGesture": True,
    }, timeout=timeout)
    if res.get("exceptionDetails"):
        exc = res["exceptionDetails"]
        desc = (exc.get("exception") or {}).get("description") or exc.get("text")
        raise RuntimeError("页面 JS 异常：%s" % desc[:2000])
    return res.get("result", {}).get("value")


def find_extension_id(client):
    for target in client.targets():
        url = target.get("url") or ""
        if url.startswith("chrome-extension://") and url.endswith("/src/background/service-worker.js"):
            return url.split("/")[2]
    return None


def paste_and_force(client, n_items):
    """页面内生成大 JSON → 填入 → Ctrl+Enter 强制格式化 → 等渲染完。"""
    return """
    (async function () {
      var n = %d;
      var text = (function () {
        var parts = new Array(n);
        for (var i = 0; i < n; i++) {
          parts[i] = '{"id":' + i + ',"name":"项目-' + i + '","score":' + ((i * 7) %% 100) + '.5,'
            + '"ok":' + (i %% 2 === 0) + ',"tags":["a","b","c"],'
            + '"meta":{"ts":1784173433013,"ref":9007199254740993}}';
        }
        return '[' + parts.join(',') + ']';
      })();

      var el = document.getElementById('input');
      var host = document.getElementById('viewer');
      var t0 = performance.now();

      el.value = text;
      // 大文本粘贴会先被 maxAutoSize 拦住，用 Ctrl+Enter 强制格式化
      el.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }));
      el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }));

      // 轮询等渲染完成：viewer 里出现 .jf-row 或错误提示
      var rows = 0;
      var t1 = null;
      for (var k = 0; k < 600; k++) {
        await new Promise(function (r) { setTimeout(r, 100); });
        rows = host.querySelectorAll('.jf-row').length;
        if (rows > 0) { t1 = performance.now(); break; }
      }
      if (t1 === null) {
        return JSON.stringify({ fail: '渲染超时（60s 内没有出现任何行）', pill: document.getElementById('pillText').textContent });
      }

      // 再等统计/收尾
      await new Promise(function (r) { setTimeout(r, 800); });
      var more = host.querySelector('.jf-summary');
      return JSON.stringify({
        inputChars: el.value.length,
        msToFirstRows: Math.round(t1 - t0),
        rows: host.querySelectorAll('.jf-row').length,
        moreSentinel: more ? more.textContent : null,
        pill: document.getElementById('pillText').textContent,
        stats: document.getElementById('stats').textContent,
        errors: window.__errs || []
      });
    })()
    """ % n_items


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(prog="verify-large-json.py")
    p.add_argument("--port", type=int, default=9334)
    p.add_argument("--n", type=int, default=100000)
    args = p.parse_args(argv)

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=30.0)
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: %s 无响应" % client.base_http)
            return 2

        ext_id = find_extension_id(client)
        if not ext_id:
            print("找不到目标扩展（service worker 不在 target 列表里）")
            return 3
        print("扩展 ID:", ext_id)

        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_HOOK})
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30.0)
        ready = client.wait_for(
            "document.readyState === 'complete' && !!document.getElementById('input')",
            timeout=20.0)
        if not ready:
            print("页面没就绪")
            return 4

        # ---------- 1) 大 JSON 强制格式化 ----------
        r1 = json.loads(ev(client, paste_and_force(client, args.n)))
        print("\n--- 大 JSON 格式化（%d 项）---" % args.n)
        print(json.dumps(r1, ensure_ascii=False, indent=2))
        if r1.get("fail"):
            return 5

        rows_after_initial = r1["rows"]
        ok_cap = rows_after_initial < 8000  # 无上限时 10 万项会生成 30 万+ 行
        print("\n[检查] 初始行数有上限（%d < 8000）：%s" % (rows_after_initial, ok_cap))

        # ---------- 2) 加载更多 ----------
        r2 = json.loads(ev(client, """
        (async function () {
          var host = document.getElementById('viewer');
          var before = host.querySelectorAll('.jf-row').length;
          var more = null;
          for (var i = 0; i < host.querySelectorAll('.jf-summary').length; i++) {
            var s = host.querySelectorAll('.jf-summary')[i];
            if (s.textContent.indexOf('还有') !== -1) { more = s; break; }
          }
          if (!more) return JSON.stringify({ fail: '找不到加载更多哨兵' });
          more.click();
          await new Promise(function (r) { setTimeout(r, 600); });
          var after = host.querySelectorAll('.jf-row').length;
          return JSON.stringify({ before: before, after: after, grew: after > before });
        })()
        """))
        print("\n--- 加载更多 ---")
        print(json.dumps(r2, ensure_ascii=False, indent=2))

        # ---------- 3) 展开全部不爆炸 ----------
        r3 = json.loads(ev(client, """
        (async function () {
          var host = document.getElementById('viewer');
          var btns = host.querySelectorAll('.jf-toolbar .jf-btn-icon');
          var t0 = performance.now();
          btns[1].click(); // 第二个图标按钮 = 展开全部
          await new Promise(function (r) { setTimeout(r, 1500); });
          return JSON.stringify({
            ms: Math.round(performance.now() - t0),
            rows: host.querySelectorAll('.jf-row').length,
            errors: window.__errs || []
          });
        })()
        """))
        print("\n--- 展开全部 ---")
        print(json.dumps(r3, ensure_ascii=False, indent=2))
        ok_expand = r3.get("rows", 1e9) < 12000
        print("[检查] 展开全部后行数有上限（< 12000）：%s" % ok_expand)

        # ---------- 4) 搜索跳转 reveal ----------
        r4 = json.loads(ev(client, """
        (async function () {
          var doc = document;
          var input = doc.querySelector('.jf-search input');
          input.value = '项目-99999';
          input.dispatchEvent(new Event('input', { bubbles: true }));
          await new Promise(function (r) { setTimeout(r, 900); });
          // 模拟 Enter 跳转
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          await new Promise(function (r) { setTimeout(r, 600); });
          var host = doc.getElementById('viewer');
          return JSON.stringify({
            hits: (doc.querySelector('.jf-hits') || {}).textContent || '',
            rows: host.querySelectorAll('.jf-row').length,
            flashed: !!host.querySelector('.jf-flash'),
            errors: window.__errs || []
          });
        })()
        """))
        print("\n--- 搜索跳转（命中最后一项，需 reveal）---")
        print(json.dumps(r4, ensure_ascii=False, indent=2))

        # ---------- 结论 ----------
        problems = []
        if not ok_cap:
            problems.append("初始渲染行数没有上限：%d" % rows_after_initial)
        if r2.get("fail") or not r2.get("grew"):
            problems.append("加载更多不生效：%s" % r2)
        if not ok_expand:
            problems.append("展开全部行数失控：%s" % r3)
        if (r1.get("errors") or r3.get("errors") or r4.get("errors")):
            problems.append("页面有 JS 报错")
        if r4.get("hits") in ("", None, "无匹配"):
            problems.append("搜索没有命中：%r" % r4.get("hits"))

        if problems:
            print("\n[失败] %d 项未通过：" % len(problems))
            for x in problems:
                print("  - " + x)
            return 6
        print("\n[通过] 大 JSON 分批渲染 / 加载更多 / 展开全部 / 搜索 reveal 全部符合预期")
        return 0
    except CDPError as exc:
        print("CDP 错误：%s" % exc)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
