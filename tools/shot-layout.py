#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shot-layout.py —— 拍下编辑页三种布局状态，用于核对「左右两栏是否对称」
以及「全屏下能否唤回输入栏」。

    python tools/shot-layout.py --port 9445 --out dist/shots

产出：
    layout-1-tree.png            非全屏 · 小文档（左右两栏各一条状态带，等高）
    layout-2-fullscreen.png      全屏 · 输入栏默认收起（JSON 吃满整宽）
    layout-3-fullscreen-input.png 全屏 · 点「显示输入」后输入栏回来
"""

import argparse
import json
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
from cdp import CDPClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = json.dumps({
    "code": "q0",
    "msg": "success",
    "data": {
        "orderId": "600653836507516928",
        "amount": 128.5,
        "paid": True,
        "refunded": None,
        "tags": ["vip", "2026-09"],
        "buyer": {"id": 10086, "nickname": "张三", "remark": "带\"引号\"、制表符\\t 和换行的备注"},
        "items": [
            {"sku": "A-1", "name": "机械键盘", "qty": 1, "price": 399},
            {"sku": "B-2", "name": "显示器支架", "qty": 2, "price": 89},
        ],
    },
    "ts": 1784173433013,
}, ensure_ascii=False, indent=2)

SETUP = r"""
(async function(){
  var inp=document.getElementById('input');
  inp.value = __SAMPLE__;
  inp.dispatchEvent(new Event('input',{bubbles:true}));
  for(var k=0;k<120;k++){
    await new Promise(function(r){setTimeout(r,40);});
    if(document.querySelector('#viewer .jf-row')) break;
  }
  await new Promise(function(r){setTimeout(r,800);});
  return 'ok';
})()
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9445)
    ap.add_argument("--out", default=str(ROOT / "dist" / "shots"))
    ap.add_argument("--ext-dir", default=str(ROOT / "dist" / "unpacked"))
    # 默认按用户实际窗口的宽高比（约 1.93）取，1440x900 太窄会让左栏头部按钮换行
    ap.add_argument("--width", type=int, default=1680)
    ap.add_argument("--height", type=int, default=870)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=60)
    try:
        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": args.width, "height": args.height,
                     "deviceScaleFactor": 1, "mobile": False})

        import hashlib
        ext = None
        for t in client.targets():
            u = t.get("url") or ""
            if u.startswith("chrome-extension://") and u.endswith("/src/background/service-worker.js"):
                ext = u.split("/")[2]
        if not ext:
            h = hashlib.sha256(str(args.ext_dir).encode("utf-16-le")).hexdigest()[:32]
            ext = "".join(chr(ord("a") + int(c, 16)) for c in h)

        def reopen():
            client.navigate("chrome-extension://%s/src/editor/editor.html" % ext, timeout=30)
            client.wait_for("document.readyState==='complete' && !!document.getElementById('input')",
                            timeout=15)
            time.sleep(0.7)

        def ev(expr):
            r = client.send("Runtime.evaluate",
                            {"expression": expr, "returnByValue": True,
                             "awaitPromise": True, "userGesture": True}, timeout=120)
            if r.get("exceptionDetails"):
                raise RuntimeError(str(r["exceptionDetails"])[:600])
            return (r.get("result") or {}).get("value")

        # 1) 非全屏 · 小文档
        reopen()
        ev(SETUP.replace("__SAMPLE__", json.dumps(SAMPLE)))
        client.screenshot(str(out / "layout-1-tree.png"))
        print("已拍 layout-1-tree.png")

        # 2) 全屏 · 输入栏默认收起
        reopen()
        ev(SETUP.replace("__SAMPLE__", json.dumps(SAMPLE)))
        ev("document.getElementById('btnFullscreen').click(); 'ok'")
        time.sleep(0.9)
        client.screenshot(str(out / "layout-2-fullscreen.png"))
        print("已拍 layout-2-fullscreen.png")

        # 3) 全屏 · 点「显示输入」
        ev("document.getElementById('btnSolo').click(); 'ok'")
        time.sleep(0.7)
        client.screenshot(str(out / "layout-3-fullscreen-input.png"))
        print("已拍 layout-3-fullscreen-input.png")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
