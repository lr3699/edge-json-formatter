#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe-ext-toolbar.py —— 扩展（页面接管）路径下，小 JSON / 大 JSON 的工具条按钮对比。

页面接管时查看器挂在 #__jf_page_host__ 的 ShadowRoot 里，页面侧 querySelector
看不到，必须穿透。

前置：Edge 已带 `--load-extension=<dist/unpacked> --remote-debugging-port=<port>` 启动。

用法：python tools/probe-ext-toolbar.py --port 9334
"""

import argparse
import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SMALL = ROOT / "tools" / "fixtures" / "page-small.json"
BIG = ROOT / "tools" / "fixtures" / "big-menu.json"

SHADOW_PRELUDE = (
    "function S(){var h=document.getElementById('__jf_page_host__');"
    "return (h&&h.shadowRoot)?h.shadowRoot:null;}"
)

DUMP = r"""
(function(){
  function S(){var h=document.getElementById('__jf_page_host__');return (h&&h.shadowRoot)?h.shadowRoot:null;}
  var sr = S();
  if (!sr) return JSON.stringify({hosted:false});
  function vis(e){
    if(!e) return false;
    if(e.hidden) return false;
    var cs=getComputedStyle(e);
    if(cs.display==='none'||cs.visibility==='hidden') return false;
    return e.offsetWidth>0||e.offsetHeight>0;
  }
  var out={hosted:true, groups:[]};
  function dump(name, root){
    if(!root) return;
    var bs=root.querySelectorAll('button');
    if(!bs.length) return;
    var list=[];
    for(var i=0;i<bs.length;i++){
      var e=bs[i];
      list.push({text:(e.textContent||'').trim(), cls:e.className, visible:vis(e)});
    }
    out.groups.push({where:name, count:list.length, buttons:list});
  }
  dump('工具条 .jf-toolbar', sr.querySelector('.jf-toolbar'));
  dump('状态带 .jf-status', sr.querySelector('.jf-status'));
  var tb = sr.querySelector('.jf-toolbar');
  out.toolbarBtns = tb ? tb.querySelectorAll('button').length : -1;
  var body = sr.querySelector('.jf-body');
  out.bodyRows = body ? body.querySelectorAll('.jf-row').length : -1;
  out.statusText = (sr.querySelector('.jf-status')||{}).textContent || '';
  return JSON.stringify(out);
})()
"""


def serve(root_dir):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root_dir), **kw)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def show(tag, res):
    print("=" * 68)
    print("[%s]" % tag)
    if not res.get("hosted"):
        print("  页面没被接管（没有 #__jf_page_host__）")
        return
    print("  工具条按钮数: %s    视口行数: %s" % (res.get("toolbarBtns"), res.get("bodyRows")))
    print("  状态带文字: %s" % (res.get("statusText", "").strip()[:120]))
    for g in res.get("groups") or []:
        vis = [b for b in g["buttons"] if b["visible"]]
        print("  [%s] 共 %d，可见 %d" % (g["where"], g["count"], len(vis)))
        for b in g["buttons"]:
            print("    %s %-12s %s" % ("√" if b["visible"] else "×", b["text"] or "(图标)", b["cls"]))


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9334)
    args = ap.parse_args(argv)

    srv = serve(ROOT)
    port = srv.server_address[1]
    print("本地服务 http://127.0.0.1:%d" % port)

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP_UNREACHABLE: %d" % args.port)
        return 2
    c.ensure_page()
    c.send("Page.enable")
    c.send("Runtime.enable")

    for tag, f in (("小 JSON", SMALL), ("大 JSON (11.7MB)", BIG)):
        url = "http://127.0.0.1:%d/tools/fixtures/%s" % (port, f.name)
        c.navigate(url, timeout=120)
        c.wait_for("!!document.getElementById('__jf_page_host__')", timeout=40)
        time.sleep(2.5)
        res = c.send("Runtime.evaluate",
                     {"expression": DUMP, "returnByValue": True, "awaitPromise": True},
                     timeout=120)
        if res.get("exceptionDetails"):
            print("异常:", str(res["exceptionDetails"])[:500])
            continue
        show(tag, json.loads(res["result"]["value"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
