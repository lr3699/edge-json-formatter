#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shot-bigview.py —— 在已加载扩展的浏览器里打开编辑页、粘贴一份大 JSON，
把「大文档视图」的实际渲染结果截图下来（用于验收与商店素材）。

用法：
    python tools/shot-bigview.py --port 9444 --http-port 18560 \
        --fixture tools/fixtures/big-menu.json --out dist/shot-bigview.png
"""

import argparse
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
from cdp import CDPClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def make_handler(fixture_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = fixture_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def ext_id_of(client, ext_dir):
    import hashlib
    for t in client.targets():
        u = t.get("url") or ""
        if u.startswith("chrome-extension://") and u.endswith("/src/background/service-worker.js"):
            return u.split("/")[2]
    h = hashlib.sha256(str(ext_dir).encode("utf-16-le")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in h)


def ev(client, expr, timeout=300.0):
    res = client.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True,
                       "userGesture": True}, timeout=timeout)
    if res.get("exceptionDetails"):
        raise RuntimeError(str(res["exceptionDetails"])[:800])
    return res.get("result", {}).get("value")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9444)
    ap.add_argument("--http-port", type=int, default=18560)
    ap.add_argument("--fixture", default=str(ROOT / "tools" / "fixtures" / "big-menu.json"))
    ap.add_argument("--out", default=str(ROOT / "dist" / "shot-bigview.png"))
    ap.add_argument("--dark", action="store_true", help="用深色主题截图")
    ap.add_argument("--scroll", type=int, default=0, help="滚动位置（px）")
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", args.http_port), make_handler(Path(args.fixture)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=60)
    try:
        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        ext = ext_id_of(client, ROOT / "dist" / "unpacked")
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext, timeout=30)
        client.wait_for("document.readyState==='complete' && !!document.getElementById('input')",
                        timeout=15)
        time.sleep(0.9)

        info = ev(client, r"""
            (async function(){
              var big=document.getElementById('bigView');
              if (%s) { await new Promise(function(r){ chrome.storage.sync.set({theme:'dark'}, r); }); }
              else    { await new Promise(function(r){ chrome.storage.sync.set({theme:'light'}, r); }); }
              await new Promise(function(r){setTimeout(r,400);});
              var text=await (await fetch('http://127.0.0.1:%d/')).text();
              var t0=performance.now();
              var dt=new DataTransfer(); dt.setData('text/plain', text);
              document.dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:dt,bubbles:true,cancelable:true}));
              for(var k=0;k<400;k++){
                await new Promise(function(r){setTimeout(r,50);});
                if(big.querySelector('.cm-line')) break;
              }
              await new Promise(function(r){setTimeout(r,700);});
              var sc=big.querySelector('.cm-scroller');
              if(sc && %d) { sc.scrollTop=%d; await new Promise(function(r){setTimeout(r,500);}); }
              return JSON.stringify({
                ms:Math.round(performance.now()-t0),
                pill:document.getElementById('pillText').textContent,
                msg:document.getElementById('msg').textContent
              });
            })()
        """ % ("true" if args.dark else "false", args.http_port, args.scroll, args.scroll))
        print("渲染结果：", info)
        client.screenshot(args.out)
        print("截图：", args.out)
        return 0
    finally:
        client.close()
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
