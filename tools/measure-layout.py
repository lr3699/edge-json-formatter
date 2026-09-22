#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure-layout.py —— 量一遍编辑页的垂直空间分配，定位「JSON 区域不够大」到底是被谁吃掉的。

在已加载扩展的浏览器里打开编辑页、粘贴夹具、然后打印各元素的高度与位置。

用法：
    python tools/measure-layout.py --port 9444 --http-port 18570 [--fixture tools/fixtures/big-menu.json]
"""

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
from cdp import CDPClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

PROBE = r"""
(async function(){
  var big=document.getElementById('bigView');
  var text=await (await fetch('http://127.0.0.1:__HTTP_PORT__/')).text();
  var dt=new DataTransfer(); dt.setData('text/plain', text);
  document.dispatchEvent(new ClipboardEvent('paste',
    {clipboardData:dt,bubbles:true,cancelable:true}));
  for(var k=0;k<400;k++){
    await new Promise(function(r){setTimeout(r,50);});
    if(big.querySelector('.cm-line')) break;
  }
  await new Promise(function(r){setTimeout(r,700);});

  function box(sel){
    var e=document.querySelector(sel);
    if(!e) return null;
    var r=e.getBoundingClientRect();
    var cs=getComputedStyle(e);
    return {top:Math.round(r.top), bottom:Math.round(r.bottom),
            h:Math.round(r.height), w:Math.round(r.width),
            pad:(cs.paddingTop+' '+cs.paddingBottom),
            fs:cs.fontSize, lh:cs.lineHeight,
            hidden:!!e.hidden, disp:cs.display};
  }
  var vh=window.innerHeight, vw=window.innerWidth;
  var ws=document.querySelector('.workspace');
  var wcs=getComputedStyle(ws);
  var sc=document.querySelector('#bigView .cm-scroller');
  return JSON.stringify({
    viewport:{w:vw,h:vh},
    body:{scrollH:document.body.scrollHeight, clientH:document.body.clientHeight,
          overflowY:getComputedStyle(document.body).overflowY},
    topbar: box('.topbar'),
    workspace: box('.workspace'),
    workspacePad: wcs.padding,
    workspaceCols: wcs.gridTemplateColumns,
    workspaceRows: wcs.gridTemplateRows,
    panelInput: box('#panelInput'),
    panelOutput: box('#panelOutput'),
    panelHeadOut: box('#panelOutput .panel-head'),
    footIn: box('#panelInput .panel-foot'),
    footOut: box('#panelOutput .panel-foot'),
    bigView: box('#bigView'),
    cmScroller: sc?{clientH:sc.clientHeight, scrollH:sc.scrollHeight}:null,
    msgs:{inText:(document.getElementById('stats')||{}).textContent,
          inFile:(document.getElementById('fileInfo')||{}).textContent,
          pill:(document.getElementById('pillText')||{}).textContent,
          msg:(document.getElementById('msg')||{}).textContent}
  });
})()
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9444)
    ap.add_argument("--http-port", type=int, default=18570)
    ap.add_argument("--fixture", default=str(ROOT / "tools" / "fixtures" / "big-menu.json"))
    ap.add_argument("--ext-dir", default=str(ROOT / "dist" / "unpacked"))
    args = ap.parse_args()

    fixture = Path(args.fixture)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = fixture.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", args.http_port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=60)
    try:
        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        import hashlib
        ext = None
        for t in client.targets():
            u = t.get("url") or ""
            if u.startswith("chrome-extension://") and u.endswith("/src/background/service-worker.js"):
                ext = u.split("/")[2]
        if not ext:
            h = hashlib.sha256(str(args.ext_dir).encode("utf-16-le")).hexdigest()[:32]
            ext = "".join(chr(ord("a") + int(c, 16)) for c in h)
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext, timeout=30)
        client.wait_for("document.readyState==='complete' && !!document.getElementById('input')",
                        timeout=15)
        time.sleep(0.9)

        res = client.send("Runtime.evaluate",
                          {"expression": PROBE.replace("__HTTP_PORT__", str(args.http_port)),
                           "returnByValue": True, "awaitPromise": True, "userGesture": True},
                          timeout=300)
        if res.get("exceptionDetails"):
            raise RuntimeError(str(res["exceptionDetails"])[:900])
        d = json.loads(res["result"]["value"])

        vh = d["viewport"]["h"]
        print("视口 %sx%s   body.scrollH=%s clientH=%s overflowY=%s"
              % (d["viewport"]["w"], vh, d["body"]["scrollH"], d["body"]["clientH"],
                 d["body"]["overflowY"]))
        print()
        print("%-22s %6s %6s %6s   %s" % ("元素", "top", "bottom", "高", "备注"))
        for key in ["topbar", "panelInput", "panelHeadOut", "footIn", "footOut",
                    "panelOutput", "bigView"]:
            b = d.get(key)
            if b is None:
                print("%-22s %s" % (key, "（不存在）"))
                continue
            print("%-22s %6s %6s %6s   pad=%s fs=%s lh=%s"
                  % (key, b["top"], b["bottom"], b["h"], b["pad"], b["fs"], b["lh"]))
        sc = d.get("cmScroller")
        if sc:
            print("%-22s %s" % ("cm-scroller", "clientH=%s scrollH=%s（=可见行高）"
                                % (sc["clientH"], sc["scrollH"])))
        print()
        ws = d["workspace"]
        print("workspace: top=%s bottom=%s h=%s padding=%s"
              % (ws["top"], ws["bottom"], ws["h"], d["workspacePad"]))
        print("workspace 列=%s" % d["workspaceCols"])
        print("workspace 行=%s" % d["workspaceRows"])
        print()
        print("底部文字：")
        for k, v in d["msgs"].items():
            print("   %-8s %s" % (k, v))
        print()

        # 空间账本
        def h_of(k):
            b = d.get(k)
            return b["h"] if b else 0

        tb = h_of("topbar")
        ws_h = ws["h"]
        out_head = h_of("panelHeadOut")
        out_foot = h_of("footOut")
        big = h_of("bigView")
        print("垂直账本（总计 %s）：topbar %s + workspace %s" % (vh, tb, ws_h))
        print("  输出面板内：panel-head %s + bigView %s + panel-foot %s = %s（面板高 %s）"
              % (out_head, big, out_foot, out_head + big + out_foot, h_of("panelOutput")))
        print("  JSON 可见行数 ≈ %s 行（按 21px 行高估）"
              % (sc["clientH"] // 21 if sc else 0))
        print("  大文档视图占视口比例 = %.1f%%" % (big / vh * 100))
        print("  输入栏：%s" % ("已收起（单栏）" if h_of("panelInput") == 0 else "展开，宽 %s"
                                % d["panelInput"]["w"]))
        return 0
    finally:
        client.close()
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
