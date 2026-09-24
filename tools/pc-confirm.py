#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pc-confirm.py —— 找到可见 Confirm 按钮的中心坐标，用真实鼠标事件点击。

为什么按坐标：异常重试后页面可能同时存在多个 Confirm 候选（一个可见、
若干残留），click-button.js 的「最靠上、最靠右」会点错；innerText 在
shadow DOM 里的元素 .click() 也不总生效。坐标 + Input.dispatchMouseEvent
是唯一稳定路径。候选多个时取**可见面积最大**的（模态框上那个真按钮）。

用法：python tools/pc-confirm.py [--port 9222] [--wait 30]
"""
import argparse
import json
import sys
import time
from pathlib import Path

CDP_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(CDP_SCRIPTS))
from cdp import CDPClient  # noqa: E402

FIND_CONFIRM = r"""
(function(){
  function deepAll(sel, root, acc){
    root = root||document; acc = acc||[];
    var hit; try{ hit = root.querySelectorAll(sel);}catch(e){ hit=[]; }
    for (var i=0;i<hit.length;i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j=0;j<ns.length;j++){ if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc); }
    return acc;
  }
  var cands = deepAll('button, v6_he-button, [role=button]').filter(function(b){
    return (b.innerText||'').trim() === 'Confirm' && b.getBoundingClientRect().width > 0;
  });
  if (!cands.length) return JSON.stringify({ok:false, reason:'NO_CONFIRM'});
  cands.sort(function(a,b){
    var ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
    return (rb.width*rb.height) - (ra.width*ra.height);
  });
  var r = cands[0].getBoundingClientRect();
  return JSON.stringify({ok:true, n:cands.length,
                         cx: Math.round(r.x + r.width/2), cy: Math.round(r.y + r.height/2)});
})()
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--wait", type=float, default=30.0, help="最长等待秒数")
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=120.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Page.bringToFront")

    t0 = time.time()
    while time.time() - t0 < args.wait:
        try:
            r = c.send("Runtime.evaluate", {
                "expression": FIND_CONFIRM, "returnByValue": True,
                "awaitPromise": True, "userGesture": True,
            }, timeout=30)
            val = r.get("result", {}).get("value")
            d = json.loads(val) if isinstance(val, str) else val
        except Exception as exc:
            print("查询异常：%s" % str(exc)[:120], file=sys.stderr)
            d = {}
        if d.get("ok"):
            cx, cy = d["cx"], d["cy"]
            for etype in ("mousePressed", "mouseReleased"):
                c.send("Input.dispatchMouseEvent", {
                    "type": etype, "x": cx, "y": cy,
                    "button": "left", "clickCount": 1,
                })
            print("已点击 Confirm (%d, %d)，候选 %d 个" % (cx, cy, d.get("n", 0)))
            return 0
        time.sleep(0.6)
    print("等待 %ds 内未出现 Confirm" % args.wait, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
