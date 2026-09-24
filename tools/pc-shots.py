#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pc-shots.py —— 管理 Partner Center Store listings 的 Screenshot/s 区块。

背景：每张截图缩略图的删除按钮是 `button.icon-button.delete`，
aria-label 形如 "Delete screenshot <文件名>"，点击后弹 Confirm 模态框。
删除是**逐一**进行的（每次删一张、确认一次）。

子命令：
    list         列出当前截图（按文件名）
    delete-all   逐张删除全部截图
    upload       向截图 input 依次上传多张 PNG（每张间隔等待）

用法：
    python tools/pc-shots.py list --port 9222
    python tools/pc-shots.py delete-all --port 9222
    python tools/pc-shots.py upload a.png b.png ... --port 9222
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CDP_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(CDP_SCRIPTS))
from cdp import CDPClient  # noqa: E402

LIST_SHOTS = r"""
(function(){
  function deepAll(sel, root, acc){
    root = root||document; acc = acc||[];
    var hit; try{ hit = root.querySelectorAll(sel);}catch(e){ hit=[]; }
    for (var i=0;i<hit.length;i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j=0;j<ns.length;j++){ if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc); }
    return acc;
  }
  var btns = deepAll('button.icon-button.delete').filter(function(b){
    var a = (b.getAttribute('aria-label')||'');
    return /^delete screenshot/i.test(a.trim());
  });
  var out = btns.map(function(b){
    var r = b.getBoundingClientRect();
    return { label:(b.getAttribute('aria-label')||'').trim(),
             y: Math.round(r.y), x: Math.round(r.x), w: Math.round(r.width) };
  });
  out.sort(function(a,b){ return a.y - b.y; });
  return JSON.stringify({ count: out.length, shots: out });
})()
"""

CLICK_SHOT_DELETE = r"""
(function(){
  function deepAll(sel, root, acc){
    root = root||document; acc = acc||[];
    var hit; try{ hit = root.querySelectorAll(sel);}catch(e){ hit=[]; }
    for (var i=0;i<hit.length;i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j=0;j<ns.length;j++){ if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc); }
    return acc;
  }
  var btns = deepAll('button.icon-button.delete').filter(function(b){
    var a = (b.getAttribute('aria-label')||'');
    return /^delete screenshot/i.test(a.trim());
  });
  btns.sort(function(a,b){ return a.getBoundingClientRect().y - b.getBoundingClientRect().y; });
  if (!btns.length) return JSON.stringify({ok:false, reason:'NONE'});
  var el = btns[window.__JF_IDX || 0];
  el.click();
  return JSON.stringify({ok:true, label:(el.getAttribute('aria-label')||'').trim()});
})()
"""

CLICK_CONFIRM = r"""
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
  if (!cands.length) return JSON.stringify({ok:false, reason:'NO_CONFIRM', n:0});
  // 全部候选按可见面积排序，取**面积最大**的（模态框上那个真实按钮），
  // 避免残留隐藏节点干扰
  cands.sort(function(a,b){
    var ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
    return (rb.width*rb.height) - (ra.width*ra.height);
  });
  var r = cands[0].getBoundingClientRect();
  return JSON.stringify({ok:true, n:cands.length,
                         cx: Math.round(r.x + r.width/2), cy: Math.round(r.y + r.height/2)});
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
    return r.get("result", {}).get("value")


def jload(v):
    return json.loads(v) if isinstance(v, str) else v


def wait(c, expr, timeout=40, interval=0.6):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if ev(c, expr):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def cmd_list(c):
    d = jload(ev(c, LIST_SHOTS))
    print("当前截图 %d 张：" % d["count"])
    for i, s in enumerate(d["shots"]):
        print("  [%d] %s  (y=%d w=%d)" % (i, s["label"], s["y"], s["w"]))
    return 0


def cmd_delete_all(c):
    for round_no in range(12):
        d = jload(ev(c, LIST_SHOTS))
        n = d["count"]
        if n == 0:
            print("全部截图已删除")
            return 0
        first = d["shots"][0]
        ev(c, "window.__JF_IDX=0;")
        res = jload(ev(c, CLICK_SHOT_DELETE))
        if not res.get("ok"):
            print("点击删除失败：%s" % res)
            return 1
        print("点击删除：%s" % res.get("label"))
        # 轮询找 Confirm 的**中心坐标**（候选可能不止一个，按可见面积取最大的），
        # 然后用真实鼠标事件按坐标点击 —— 绕开选择器歧义
        confirmed = False
        for _ in range(40):
            time.sleep(0.6)
            try:
                res = jload(ev(c, CLICK_CONFIRM))
            except Exception as exc:
                print("  Confirm 查询异常：%s" % str(exc)[:120])
                continue
            if res.get("ok"):
                c.send("Page.bringToFront")
                for etype in ("mousePressed", "mouseReleased"):
                    c.send("Input.dispatchMouseEvent", {
                        "type": etype, "x": res["cx"], "y": res["cy"],
                        "button": "left", "clickCount": 1,
                    })
                confirmed = True
                print("  坐标点击 Confirm (%d, %d)，候选 %d 个" % (res["cx"], res["cy"], res.get("n", 0)))
                break
        if not confirmed:
            print("Confirm 按钮未出现", file=sys.stderr)
            return 1
        time.sleep(0.5)
        # 等数量减少
        t0 = time.time()
        while time.time() - t0 < 30:
            time.sleep(1.2)
            d2 = jload(ev(c, LIST_SHOTS))
            if d2["count"] < n:
                break
        else:
            print("数量未减少（%d -> %d）" % (n, d2["count"]), file=sys.stderr)
            return 1
        print("  剩余 %d 张" % d2["count"])
        time.sleep(1.0)
    return 0


def cmd_upload(c, files, wait_each=12.0):
    ok_all = True
    for i, f in enumerate(files):
        p = Path(f)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            print("文件不存在：%s" % p, file=sys.stderr)
            ok_all = False
            continue
        # 每次都重新定位 input（Angular 会重建）
        node = c.send("Runtime.evaluate", {"expression": FIND_SHOT_INPUT, "returnByValue": False},
                      timeout=60).get("result", {})
        obj = node.get("objectId")
        if not obj:
            print("找不到截图 file input", file=sys.stderr)
            return 1
        c.send("DOM.setFileInputFiles", {"files": [str(p)], "objectId": obj}, timeout=120)
        print("[%d/%d] 已注入 %s，等待上传..." % (i + 1, len(files), p.name))
        time.sleep(wait_each)
        d = jload(ev(c, LIST_SHOTS))
        print("      当前缩略图删除按钮数：%d" % d["count"])
    return 0 if ok_all else 1


FIND_SHOT_INPUT = r"""
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
  var sh = null;
  for (var i=0;i<heads.length;i++){
    var t=(heads[i].innerText||'').replace(/\s+/g,' ').trim();
    if (/screenshot\/?s/i.test(t)) { sh = heads[i]; break; }
  }
  if (!sh) return null;
  var node = sh, hops = 0;
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
    ap.add_argument("cmd", choices=["list", "delete-all", "upload"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--wait-each", type=float, default=12.0)
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=120.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()

    if args.cmd == "list":
        return cmd_list(c)
    if args.cmd == "delete-all":
        return cmd_delete_all(c)
    if args.cmd == "upload":
        if not args.files:
            print("upload 需要文件列表", file=sys.stderr)
            return 1
        return cmd_upload(c, args.files, args.wait_each)
    return 0


if __name__ == "__main__":
    sys.exit(main())
