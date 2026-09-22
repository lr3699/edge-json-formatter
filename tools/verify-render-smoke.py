#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-render-smoke.py —— 格式化结果「看得见」的冒烟验收。

背景（2026-09-22 的 P0）：`editor.js` 的大文档工具条拿到了一个**不存在的**
`#bigToolbar` 节点，`hideBigView()/showBigView()` 里又直接给它设 `hidden` ——
空指针一抛，`ensureBigView()` 之前的代码全断，于是**任何大小的 JSON 格式化后
右侧都是空白**。DOM 少一个节点不该让正文渲染整条链路陪葬。

这里把三条最要紧的路径各跑一遍，并且**监听控制台异常**（只看 DOM 是不够的，
异常被吞掉时 DOM 也会「看起来正常」）：

  1. 小 JSON  → 树视图有行、且 #viewer 可见
  2. 大 JSON  → CodeMirror 有行、且 #bigView 与 #bigToolbar 都可见
  3. 再切回小 JSON → 树视图回来了（hideBigView 这条回归路径）

用法：python tools/verify-render-smoke.py --port 9447 [--ext]
      --ext  测扩展页（chrome-extension://…/src/editor/editor.html）；
             不给则测本地站点，配合 --url。
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

fails = []
passes = []


def check(name, ok, detail=""):
    (passes if ok else fails).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  -- " + str(detail)) if detail else ""))


def make_big(n=12000):
    """造一个稳超 600KB 阈值的文档，顺便带上雪花 ID 走保真路径"""
    rows = []
    for i in range(n):
        rows.append({
            "id": 10000000000000000000 + i,   # 超过 2^53，逼出保真路径
            "name": "item-%d" % i,
            "paid": i % 2 == 0,
            "refunded": None,
            "tags": ["a", "b"],
        })
    return json.dumps({"code": "0", "data": rows}, ensure_ascii=False)


def set_input(client, text):
    client.send("Runtime.evaluate", {
        "expression": (
            "(function(t){var el=document.getElementById('input');"
            "el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}));return 'ok';})(%s)"
            % json.dumps(text)
        ),
        "returnByValue": True,
    })


def probe(client):
    res = client.send("Runtime.evaluate", {
        "expression": r"""
        (function(){
          var viewer = document.getElementById('viewer');
          var big    = document.getElementById('bigView');
          var tb     = document.getElementById('bigToolbar');
          var root   = document.querySelector('.jf-root');
          var cmc    = document.querySelector('.big-view .cm-content');
          function vis(el){ return !!el && !el.hidden && !!(el.offsetWidth||el.offsetHeight); }
          return JSON.stringify({
            viewerVisible: vis(viewer),
            bigVisible: vis(big),
            toolbarVisible: vis(tb),
            toolbarButtons: tb ? tb.querySelectorAll('button').length : -1,
            treeRows: document.querySelectorAll('.jf-row').length,
            hasRoot: !!root,
            cmLines: cmc ? cmc.childElementCount : 0,
            bigText: big ? (big.textContent||'').slice(0,60) : ''
          });
        })()
        """,
        "returnByValue": True,
    })
    return json.loads(res["result"]["value"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9447)
    ap.add_argument("--url", default="")
    ap.add_argument("--ext", action="store_true", help="测扩展内的编辑页")
    args = ap.parse_args()

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=90)
    client.ensure_page()
    client.send("Page.enable")
    client.send("Runtime.enable")
    client.send("Log.enable")

    errors = []
    # CDPClient 不带事件订阅，改成在页面里装钩子：格式化是在 input 事件里同步跑的，
    # 抛出的异常不会再冒到我们的 evaluate 里，只能靠 window.onerror 兜住。
    client.send("Page.addScriptToEvaluateOnNewDocument", {
        "source": (
            "window.__jfErrs=[];"
            "window.addEventListener('error',function(e){"
            "  window.__jfErrs.push(String(e.message||e.error));});"
            "window.addEventListener('unhandledrejection',function(e){"
            "  window.__jfErrs.push('unhandled: '+String(e.reason));});"
        )
    })

    def drain_errors():
        r = client.send("Runtime.evaluate", {
            "expression": "JSON.stringify(window.__jfErrs||[])",
            "returnByValue": True,
        })
        for e in json.loads(r["result"]["value"]):
            errors.append(e)

    url = args.url
    if args.ext:
        ext = None
        for t in client.targets():
            u = t.get("url") or ""
            if u.startswith("chrome-extension://") and u.endswith("/src/background/service-worker.js"):
                ext = u.split("/")[2]
        if not ext:
            print("找不到扩展 ID（扩展没加载？）")
            return 2
        url = "chrome-extension://%s/src/editor/editor.html" % ext

    print("目标页面：" + url)
    client.navigate(url, timeout=40)
    client.wait_for("document.readyState==='complete' && !!document.getElementById('input')", timeout=20)
    time.sleep(0.8)

    small = json.dumps({"code": "0", "msg": "success",
                        "data": {"paid": True, "refunded": None, "amount": 12.5}},
                       ensure_ascii=False)

    print("\n[1] 小 JSON → 树视图")
    set_input(client, small)
    time.sleep(1.2)
    s1 = probe(client)
    print("      " + json.dumps(s1, ensure_ascii=False))
    check("小 JSON：#viewer 可见", s1["viewerVisible"])
    check("小 JSON：树视图渲染出行", s1["hasRoot"] and s1["treeRows"] > 0,
          "rows=%d" % s1["treeRows"])
    check("小 JSON：大文档视图未抢占", not s1["bigVisible"])

    print("\n[2] 大 JSON → 虚拟化视图")
    set_input(client, make_big())
    time.sleep(3.0)
    s2 = probe(client)
    print("      " + json.dumps(s2, ensure_ascii=False))
    check("大 JSON：#bigView 可见", s2["bigVisible"])
    check("大 JSON：CodeMirror 有行", s2["cmLines"] > 0, "lines=%d" % s2["cmLines"])
    check("大 JSON：工具条可见且有按钮", s2["toolbarVisible"] and s2["toolbarButtons"] >= 6,
          "buttons=%d" % s2["toolbarButtons"])
    check("大 JSON：正文有内容", len(s2["bigText"].strip()) > 0, repr(s2["bigText"][:40]))

    print("\n[3] 切回小 JSON → 树视图要能回来")
    set_input(client, small)
    time.sleep(1.5)
    s3 = probe(client)
    print("      " + json.dumps(s3, ensure_ascii=False))
    check("回到小 JSON：#viewer 可见", s3["viewerVisible"])
    check("回到小 JSON：树视图有行", s3["treeRows"] > 0, "rows=%d" % s3["treeRows"])
    check("回到小 JSON：大视图与工具条收起", not s3["bigVisible"] and not s3["toolbarVisible"])

    drain_errors()
    real = [e for e in errors if "favicon" not in e.lower()]
    print("\n[4] 控制台异常")
    if real:
        for e in real[:8]:
            print("      ! " + e[:200])
    check("无控制台异常", not real, "%d 条" % len(real))

    print("\n汇总：%d 通过 / %d 失败" % (len(passes), len(fails)))
    if fails:
        print("失败项：" + "、".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
