#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure-store-logo.py —— 量出 Edge 加载项商店页面上 logo 的真实渲染尺寸。

为什么需要：商店 logo 交的是 300×300，但页面显示的尺寸完全不同。
选哪一版 300px 图形（「JSON」字标 vs 单字母 J），取决于**最小展示尺寸**，
而不是 300px 本身。用 CDP 打开真实商店页，读 img 的 clientWidth/Height。

用法：python tools/measure-store-logo.py [--port 9222] [--crx <id>]
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

PROBE = r"""
(function(){
  var out=[];
  document.querySelectorAll('img').forEach(function(im){
    var r=im.getBoundingClientRect();
    var w=Math.round(r.width), h=Math.round(r.height);
    if(w>=16 && w<=320 && Math.abs(w-h)<=2 && w>0){
      out.push({w:w,h:h,src:(im.currentSrc||im.src||'').slice(0,160)});
    }
  });
  // 去重：同尺寸同源只留一条
  var seen={}, uniq=[];
  out.forEach(function(o){var k=o.w+'|'+o.h+'|'+o.src; if(!seen[k]){seen[k]=1;uniq.push(o);}});
  return JSON.stringify({url:location.href, title:document.title, imgs:uniq}, null, 2);
})()
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--crx", default="lckjaaoekeleokmdnjjfagoohghjflcn")
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=120.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})

    targets = [
        ("详情页", "https://microsoftedge.microsoft.com/addons/detail/%s" % args.crx),
        ("搜索页", "https://microsoftedge.microsoft.com/addons/search/json%20duo"),
        ("分类页", "https://microsoftedge.microsoft.com/addons/category/Developer-Tools"),
    ]
    for label, url in targets:
        print("=" * 70)
        print("【%s】%s" % (label, url))
        try:
            c.navigate(url, timeout=60.0)
            c.wait_for("document.readyState==='complete'", timeout=30)
            import time
            time.sleep(3.5)   # 等 SPA 水合
            raw = c.evaluate(PROBE, timeout=60)
            if isinstance(raw, dict):
                raw = raw.get("value", raw)
            d = json.loads(raw)
            print("title:", d["title"][:80])
            for o in d["imgs"]:
                print("   %3dx%-3d  %s" % (o["w"], o["h"], o["src"]))
        except Exception as e:
            print("   读取失败：%s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
