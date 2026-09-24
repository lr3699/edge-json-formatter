#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pc-listing-logo.py —— 打开 Partner Center 某个语言的 Store listing 编辑面板，
把指定 PNG 注入「Extension logo」的 file input，并回报结果。

为什么单独写：
  1. reload /listings 之后 SPA 要好几秒才渲染出 Edit details，固定 sleep 会点空；
     这里用轮询等到按钮真的可点。
  2. 页面上 4 个 file input 共用 name=fileuploader，必须按「所在区块标题」定位，
     不能靠序号猜（序号虽然对，但对不上时无法发现）。
  3. `el.files` 回读是**假阴性**（Angular 上传后重建 input），所以判定成功要靠
     上传后页面上出现的新缩略图 / 是否出现错误横幅，不能靠 files 数组。

用法：
    python tools/pc-listing-logo.py --lang zh  --png icons/store-icon-300.png
    python tools/pc-listing-logo.py --lang en  --png icons/store-icon-300.png
    python tools/pc-listing-logo.py --lang zh  --png X.png --shot docs/x.png
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

LISTINGS = ("https://partner.microsoft.com/en-us/dashboard/microsoftedge/"
            "b5797b76-ba71-40f0-abd2-b1248f932cf1/listings")

# 点「第 n 个」Edit details —— 按行的 y 排序，0 = Chinese (China)，1 = English
CLICK_EDIT = r"""
(function(){
  function deepAll(sel, root, acc){
    root = root||document; acc = acc||[];
    var hit; try{ hit = root.querySelectorAll(sel);}catch(e){ hit=[]; }
    for (var i=0;i<hit.length;i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j=0;j<ns.length;j++){ if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc); }
    return acc;
  }
  var btns = deepAll('button').filter(function(b){
    return (b.innerText||'').trim() === 'Edit details' && b.getBoundingClientRect().width > 0;
  });
  btns.sort(function(a,b){ return a.getBoundingClientRect().y - b.getBoundingClientRect().y; });
  if (!btns.length) return JSON.stringify({ok:false, reason:'NO_EDIT_BTN'});
  if (btns.length <= window.__JF_ROW) return JSON.stringify({ok:false, reason:'ROW_OOR', n:btns.length});
  var el = btns[window.__JF_ROW];
  el.click();
  return JSON.stringify({ok:true, row:window.__JF_ROW, of:btns.length,
                         y:Math.round(el.getBoundingClientRect().y)});
})()
"""

# 找到「Extension logo」区块里的 file input，返回它的 objectId
FIND_LOGO_INPUT = r"""
(function(){
  function deepAll(sel, root, acc){
    root = root||document; acc = acc||[];
    var hit; try{ hit = root.querySelectorAll(sel);}catch(e){ hit=[]; }
    for (var i=0;i<hit.length;i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j=0;j<ns.length;j++){ if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc); }
    return acc;
  }
  var ins = deepAll('input[type=file]');
  for (var i=0;i<ins.length;i++){
    var node = ins[i], hops = 0, found = false;
    while (node && hops < 9){
      node = node.parentElement; hops++;
      if (!node) break;
      var hs = node.querySelectorAll('h1,h2,h3,h4,legend,label,.title,[class*=title]');
      for (var k=0;k<hs.length;k++){
        var t = (hs[k].innerText||'').replace(/\s+/g,' ').trim();
        if (/extension logo/i.test(t)) { found = true; break; }
      }
      if (found) break;
    }
    if (found) return ins[i];
  }
  return null;
})()
"""

# 读页面状态：错误横幅 / 面板标题 / logo 缩略图数量
STATE = r"""
(function(){
  function deepAll(sel, root, acc){
    root = root||document; acc = acc||[];
    var hit; try{ hit = root.querySelectorAll(sel);}catch(e){ hit=[]; }
    for (var i=0;i<hit.length;i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j=0;j<ns.length;j++){ if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc); }
    return acc;
  }
  var body = document.body.innerText || '';
  var err = null;
  var m = body.match(/Something went wrong[^\n]*/);
  if (m) err = m[0].slice(0, 140);
  var title = null;
  deepAll('h1,h2,h3').forEach(function(h){
    var t=(h.innerText||'').trim();
    if (/^Details for/.test(t)) title = t;
  });
  return JSON.stringify({err:err, panelTitle:title, url:location.href});
})()
"""


def ev(c, expr, timeout=60):
    r = c.send("Runtime.evaluate", {
        "expression": expr, "returnByValue": True,
        "awaitPromise": True, "userGesture": True,
    }, timeout=timeout)
    if r.get("exceptionDetails"):
        exc = r["exceptionDetails"]
        raise RuntimeError((exc.get("exception") or {}).get("description") or exc.get("text"))
    v = r.get("result", {}).get("value")
    return v


def wait_js(c, expr, timeout=60, interval=0.7):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if ev(c, expr):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["zh", "en"], default="zh")
    ap.add_argument("--png", required=True)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--shot", help="上传后截图保存路径")
    ap.add_argument("--no-reload", action="store_true", help="不刷新列表页，直接用当前面板")
    args = ap.parse_args()

    png = Path(args.png)
    if not png.is_absolute():
        png = ROOT / png
    if not png.exists():
        print("文件不存在：%s" % png, file=sys.stderr)
        return 1
    row = 0 if args.lang == "zh" else 1

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=120.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1440, "height": 1100, "deviceScaleFactor": 1, "mobile": False})

    if not args.no_reload:
        c.navigate(LISTINGS, timeout=90)
        c.wait_for("document.readyState==='complete'", timeout=60)
        ev(c, "window.__JF_ROW=%d;" % row)
        ok = wait_js(c, "document.querySelectorAll('button').length>0", timeout=40)
        # 等 Edit details 真的渲染出来
        ready = wait_js(c, r"""
          (function(){
            var f=false;
            function d(root){ root.querySelectorAll('button').forEach(function(b){
              if((b.innerText||'').trim()==='Edit details' && b.getBoundingClientRect().width>0) f=true; });
              root.querySelectorAll('*').forEach(function(n){ if(n.shadowRoot) d(n.shadowRoot); });
            } d(document); return f; })()
        """, timeout=45)
        print("列表页就绪：%s" % ready)
        if not ready:
            print("等不到 Edit details 按钮，放弃", file=sys.stderr)
            return 1
        res = ev(c, "window.__JF_ROW=%d; %s" % (row, CLICK_EDIT))
        print("点击 Edit details：%s" % res)
        if json.loads(res).get("ok") is not True:
            return 1
    else:
        ev(c, "window.__JF_ROW=%d;" % row)

    # 等编辑面板里的 logo 输入出现（必须用 objectId 方式注入）
    time.sleep(2.5)
    ok = wait_js(c, "/^Details for/.test(document.body.innerText)", timeout=30)
    print("编辑面板已展开：%s" % ok)
    time.sleep(2.0)

    node = c.send("Runtime.evaluate", {
        "expression": FIND_LOGO_INPUT, "returnByValue": False,
    }, timeout=60).get("result", {})
    obj_id = node.get("objectId")
    if not obj_id:
        print("找不到 Extension logo 的 file input", file=sys.stderr)
        return 1
    c.send("DOM.setFileInputFiles", {"files": [str(png)], "objectId": obj_id}, timeout=120)
    print("已注入文件：%s" % png.name)

    time.sleep(12)
    st = json.loads(ev(c, STATE))
    print("页面状态：%s" % json.dumps(st, ensure_ascii=False))

    if args.shot:
        sp = Path(args.shot)
        if not sp.is_absolute():
            sp = ROOT / sp
        sp.parent.mkdir(parents=True, exist_ok=True)
        got = c.send("Page.captureScreenshot", {"format": "png"})
        import base64
        sp.write_bytes(base64.b64decode(got["data"]))
        print("截图：%s" % sp.relative_to(ROOT))

    return 0 if not st.get("err") else 3


if __name__ == "__main__":
    sys.exit(main())
