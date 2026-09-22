#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure-tree-layout.py —— 小文档（树视图）下的横向/纵向空间账本。

针对两个用户反馈：
  1) 非全屏时右栏底部像是「白占了一块」，左右两栏高度分布不对称；
  2) 全屏时点「显示输入」没反应。

本脚本量出左右两栏各自「头部 / 内容 / 底部条」的高度，看清右栏底部
是否叠了两条状态带（树视图自带的 .jf-status + 面板的 .panel-foot）。

用法：
    python tools/measure-tree-layout.py --port 9445 [--mode tree|fullscreen|fullscreen-input]
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

# 一份小 JSON：走树视图，节点数与截图里那类样本同量级
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


def box_js(sel):
    return """
function box(sel){
  var e=document.querySelector(sel);
  if(!e) return null;
  var r=e.getBoundingClientRect();
  var cs=getComputedStyle(e);
  return {t:Math.round(r.top),b:Math.round(r.bottom),h:Math.round(r.height),w:Math.round(r.width),
          disp:cs.display, pad:cs.paddingTop+'/'+cs.paddingBottom, fs:cs.fontSize, lh:cs.lineHeight};
}
"""


PROBE = r"""
(async function(){
""" + box_js(None) + r"""
  var text = __SAMPLE__;
  // 小文本走 textarea 默认路径：合成 paste 事件不会触发浏览器默认插入，
  // 所以直接写 value 再派发 input（editor.js 的 input 监听会读 value 并调度格式化）。
  var inp = document.getElementById('input');
  inp.value = text;
  inp.dispatchEvent(new Event('input', {bubbles:true}));
  for(var k=0;k<120;k++){
    await new Promise(function(r){setTimeout(r,40);});
    if(document.querySelector('#viewer .jf-row')) break;
  }
  await new Promise(function(r){setTimeout(r,600);});

  __ACTION__

  await new Promise(function(r){setTimeout(r,450);});

  var ws=document.querySelector('.workspace');
  var wcs=getComputedStyle(ws);
  var jfs=document.querySelector('#viewer .jf-status');
  var jft=document.querySelector('#viewer .jf-toolbar');
  return JSON.stringify({
    viewport:{w:innerWidth,h:innerHeight},
    ws:{h:Math.round(ws.getBoundingClientRect().height),
        cols:wcs.gridTemplateColumns, rows:wcs.gridTemplateRows,
        cls:ws.className},
    body:{scrollH:document.body.scrollHeight, clientH:document.body.clientHeight,
          cls:document.body.className},
    inPanel:box('#panelInput'),
    inHead:box('#panelInput .panel-head'),
    inWrap:box('#panelInput .editor-wrap'),
    inFoot:box('#panelInput .panel-foot'),
    outPanel:box('#panelOutput'),
    outViewer:box('#viewer'),
    outToolbar:box('#viewer .jf-toolbar'),
    jfStatus:box('#viewer .jf-status'),
    viewInfo:box('#viewInfo'),
    outFoot:box('#panelOutput .panel-foot'),
    jfStatusText:jfs?jfs.textContent.trim():null,
    texts:{stats:(document.getElementById('stats')||{}).textContent,
           viewInfo:(document.getElementById('viewInfo')||{}).textContent,
           pill:(document.getElementById('pillText')||{}).textContent,
           msg:(document.getElementById('msg')||{}).textContent},
    solo:{btn:!!document.getElementById('btnSolo'),
          pressed:(document.getElementById('btnSolo')||{getAttribute:function(){return null;}})
                   .getAttribute('aria-pressed'),
          label:(document.getElementById('soloLabel')||{}).textContent},
    fs:document.documentElement.className
  });
})()
"""

ACTIONS = {
    "tree": "",  # 非全屏、小文档
    "fullscreen": "document.getElementById('btnFullscreen').click();",
    "fullscreen-input": ("document.getElementById('btnFullscreen').click();"
                         "await new Promise(function(r){setTimeout(r,300);});"
                         "document.getElementById('btnSolo').click();"),
    "solo": "document.getElementById('btnSolo').click();",
}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9445)
    ap.add_argument("--mode", default="tree", choices=sorted(ACTIONS))
    ap.add_argument("--ext-dir", default=str(ROOT / "dist" / "unpacked"))
    args = ap.parse_args()

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
        time.sleep(0.8)

        expr = PROBE.replace("__SAMPLE__", json.dumps(SAMPLE)).replace("__ACTION__", ACTIONS[args.mode])
        res = client.send("Runtime.evaluate",
                          {"expression": expr, "returnByValue": True,
                           "awaitPromise": True, "userGesture": True},
                          timeout=120)
        if res.get("exceptionDetails"):
            raise RuntimeError(str(res["exceptionDetails"])[:900])
        d = json.loads(res["result"]["value"])

        print("模式 %s    视口 %sx%s" % (args.mode, d["viewport"]["w"], d["viewport"]["h"]))
        print("body.class = %r    html.class = %r" % (d["body"]["cls"], d["fs"]))
        print("workspace  高=%s 列=%s 行=%s  cls=%r"
              % (d["ws"]["h"], d["ws"]["cols"], d["ws"]["rows"], d["ws"]["cls"]))
        print()
        print("%-26s %6s %6s %6s %6s  %s" % ("元素", "top", "bottom", "高", "宽", "备注"))
        rows = [("输入·面板", "inPanel"), ("输入·头部", "inHead"), ("输入·输入框", "inWrap"),
                ("输入·底部条", "inFoot"),
                ("输出·面板", "outPanel"), ("输出·查看器", "outViewer"),
                ("输出·工具条", "outToolbar"), ("输出·jf-status", "jfStatus"),
                ("输出·底部条", "outFoot")]
        for label, key in rows:
            b = d.get(key)
            if not b:
                print("%-26s %s" % (label, "（不存在）"))
                continue
            print("%-26s %6s %6s %6s %6s  disp=%s pad=%s lh=%s"
                  % (label, b["t"], b["b"], b["h"], b["w"], b["disp"], b["pad"], b["lh"]))

        print()
        print("底部文案：")
        for k, v in d["texts"].items():
            print("   %-6s %s" % (k, v))
        print("   jf-status %s" % d["jfStatusText"])
        print()
        print("solo 按钮：存在=%s aria-pressed=%s 文案=%r"
              % (d["solo"]["btn"], d["solo"]["pressed"], d["solo"]["label"]))

        # 关键账本
        def h(k):
            b = d.get(k)
            return b["h"] if b else 0

        print()
        print("【空间账本】")
        print("  左栏 = 头部 %s + 输入框 %s + 底部条 %s = %s"
              % (h("inHead"), h("inWrap"), h("inFoot"),
                 h("inHead") + h("inWrap") + h("inFoot")))
        out_strips = [("jf-status", h("jfStatus")), ("panel-foot", h("outFoot"))]
        print("  右栏 = 工具条(在查看器内) %s + 查看器 %s + 底部条 %s = %s"
              % (h("outToolbar"), h("outViewer"), h("outFoot"),
                 h("outToolbar") + h("outViewer") + h("outFoot")))
        print("  右栏底部叠了几条状态带：")
        total = 0
        for name, hh in out_strips:
            if hh:
                total += hh
                print("     · %-12s %s px" % (name, hh))
        print("     合计 %s px（这就是截图里被圈住的那块）" % total)
        print("  左栏底部只有 1 条：%s px" % h("inFoot"))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
