#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pc-promo.py —— 按**区块标题**定位 Partner Center 表单里的 file input 并上传。

为什么按标题而不是序号：页面上 4 个上传位共用 name=fileuploader，
序号会随「某区块是否已有图」而漂移；标题永远稳定。

用法：
    python tools/pc-promo.py --heading "small promotional" --png docs/chrome-assets/promo-small-440x280.png
    python tools/pc-promo.py --heading "large promotional" --png docs/chrome-assets/promo-marquee-1400x560.png
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CDP_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(CDP_SCRIPTS))
from cdp import CDPClient  # noqa: E402

FIND_INPUT = r"""
(function(){
  function deepAll(sel, root, acc){
    root = root||document; acc = acc||[];
    var hit; try{ hit = root.querySelectorAll(sel);}catch(e){ hit=[]; }
    for (var i=0;i<hit.length;i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j=0;j<ns.length;j++){ if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc); }
    return acc;
  }
  var heads = deepAll('h1,h2,h3,h4,legend,label,.title,[class*=title]');
  var target = null;
  for (var i=0;i<heads.length;i++){
    var t=(heads[i].innerText||'').replace(/\s+/g,' ').trim();
    if (new RegExp(window.__JF_HEAD,'i').test(t)) { target = heads[i]; break; }
  }
  if (!target) return null;
  var node = target, hops = 0;
  while (node && hops < 14){
    node = node.parentElement; hops++;
    if (!node) break;
    var ins = node.querySelectorAll('input[type=file]');
    if (ins.length) return ins[0];
  }
  return null;
})()
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--heading", required=True, help="区块标题的正则片段")
    ap.add_argument("--png", required=True)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--shot", help="上传后截图路径")
    args = ap.parse_args()

    png = Path(args.png)
    if not png.is_absolute():
        png = ROOT / png
    if not png.exists():
        print("文件不存在：%s" % png, file=sys.stderr)
        return 1

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=120.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Page.bringToFront")

    r = c.send("Runtime.evaluate", {
        "expression": "window.__JF_HEAD=%s;" % json.dumps(args.heading),
        "returnByValue": True, "userGesture": True,
    }, timeout=30)
    if r.get("exceptionDetails"):
        print("设置变量失败", file=sys.stderr)
        return 1

    node = c.send("Runtime.evaluate", {
        "expression": FIND_INPUT, "returnByValue": False,
    }, timeout=60).get("result", {})
    obj = node.get("objectId")
    if not obj:
        print("找不到标题为「%s」的区块里的 file input" % args.heading, file=sys.stderr)
        return 1
    c.send("DOM.setFileInputFiles", {"files": [str(png)], "objectId": obj}, timeout=120)
    print("已注入 %s → 区块「%s」" % (png.name, args.heading))
    time.sleep(14)

    if args.shot:
        sp = Path(args.shot)
        if not sp.is_absolute():
            sp = ROOT / sp
        sp.parent.mkdir(parents=True, exist_ok=True)
        got = c.send("Page.captureScreenshot", {"format": "png"})
        sp.write_bytes(base64.b64decode(got["data"]))
        print("截图：%s" % sp.relative_to(ROOT))

    # 报告页面是否出现错误横幅
    st = c.send("Runtime.evaluate", {
        "expression": "(function(){var m=(document.body.innerText||'').match(/Something went wrong[^\\n]*/);"
                      "return m?m[0].slice(0,120):null;})()",
        "returnByValue": True,
    }, timeout=30).get("result", {}).get("value")
    print("错误横幅：%s" % st)
    return 0 if not st else 3


import base64  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
