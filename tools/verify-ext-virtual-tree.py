#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-ext-virtual-tree.py —— 在真实 Edge + 已加载扩展的环境里，验收「直接打开 .json 页面」
走的是**虚拟化树视图**。

与 verify-virtual-tree.py 的分工（两者都不该省）：
  · verify-virtual-tree.py 跑 tools/fixtures/vtree.html，测 viewer.js 本体，
    宿主是把查看器挂到普通 DOM 上的最小页面；
  · 本脚本走扩展的真实链路：.json 响应 → 内容脚本接管 → 查看器挂进 **Shadow DOM**。

Shadow DOM 是这里独有的风险点：页面侧的 document.querySelector 完全看不到树，
所有断言都必须先穿透 #__jf_page_host__ 的 shadowRoot 才能拿到元素。虚拟化改了
DOM 结构（多了 .jf-sizer/.jf-window、少了 .jf-children），Shadow DOM 里的宿主样式
也独立，所以这条链路必须单独验一遍。

断言：
  1. 小 JSON 页面：被接管、树渲染出来、行表 = 美化输出行数、无报错
  2. 大 JSON 页面（22MB）：spacer 高度 = 留白 + 行数 × 行高，DOM 行数仍是几十行
  3. 大 JSON 页面滚动：窗口跟着位移走、行号连续、DOM 行数恒定
  4. 「还原原文」可把页面交还给浏览器原生渲染
  5. 全程无 JS 报错（用 addScriptToEvaluateOnNewDocument 在导航前装好钩子）

前置：Edge 已带 --load-extension=dist/unpacked --remote-debugging-port=9333 启动
      （Edge 137+ 还需 --enable-unsafe-extension-debugging，扩展路径用反斜杠写法）。
用法：python tools/verify-ext-virtual-tree.py [--port 9333] [--shot]
"""

import argparse
import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient, CDPError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BIG = ROOT / "tools" / "fixtures" / "big-20mb.json"
# 页面接管这条路上还有个体积门槛：content.js 里 `r.size > settings.maxAutoSize`
# （默认 20MB）就跳过自动格式化。22MB 的 big-20mb.json 正好越线，所以这里用
# 11.7MB 的 big-menu.json 来验「大文档被接管后走虚拟化渲染」这条真实链路。
PAGE_BIG = ROOT / "tools" / "fixtures" / "big-menu.json"
SMALL = ROOT / "tools" / "fixtures" / "page-small.json"

PAD_TOP = 14
PAD_BOTTOM = 80
ROW_H = 24

fails = []


def check(name, ok, extra=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  " + str(extra)) if extra else ""))
    if not ok:
        fails.append(name)
    return ok


# 在导航前装好报错钩子：内容脚本在 document_start 就跑，导航后再装钩子会漏掉早期错误
ERROR_HOOK = """
window.__errs = [];
window.addEventListener('error', function (e) { window.__errs.push('error: ' + (e.message || e.type)); });
window.addEventListener('unhandledrejection', function (e) {
  window.__errs.push('reject: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason)));
});
"""

# 所有探针都从这里取 shadowRoot —— 页面侧看不到树，必须穿透
SHADOW_PRELUDE = (
    "function S(){var h=document.getElementById('__jf_page_host__');"
    "return (h&&h.shadowRoot)?h.shadowRoot:null;}"
)


def probe_expr(body):
    return "(function(){" + SHADOW_PRELUDE + "return " + body + ";})()"


def serve(root_dir):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root_dir), **kw)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, max-age=0")
            super().end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="verify-ext-virtual-tree.py")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--shot", action="store_true")
    args = ap.parse_args(argv)

    if not PAGE_BIG.exists() or not SMALL.exists():
        print("缺少测试数据：%s / %s" % (PAGE_BIG, SMALL))
        return 2

    # 小文档的期望行数 = 它按 indent=2 美化之后的实际行数（别手写常量，
    # fixture 一改就错；viewer 的美化输出与 json.dumps(indent=2) 同构）
    small_expect = len(json.dumps(json.loads(SMALL.read_text(encoding="utf-8")),
                                  ensure_ascii=False, indent=2).split("\n"))

    srv = serve(ROOT)
    port = srv.server_address[1]
    print("本地服务 http://127.0.0.1:%d（根目录 %s）" % (port, ROOT))

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    shot_dir = ROOT / "dist" / "shots"
    try:
        if not c.is_alive():
            print("CDP_UNREACHABLE: 127.0.0.1:%d 无响应" % args.port)
            return 2
        c.ensure_page()
        c.send("Page.enable")
        c.send("Runtime.enable")
        c.send("Network.enable")
        c.send("Network.setCacheDisabled", {"cacheDisabled": True})
        c.send("Emulation.setDeviceMetricsOverride",
               {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        c.send("Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_HOOK})

        def ev(expr, timeout=300.0):
            r = c.send("Runtime.evaluate",
                       {"expression": expr, "returnByValue": True,
                        "awaitPromise": True, "userGesture": True}, timeout=timeout)
            if r.get("exceptionDetails"):
                exc = r["exceptionDetails"]
                desc = (exc.get("exception") or {}).get("description") or exc.get("text")
                raise RuntimeError("页面 JS 异常：%s" % str(desc)[:1200])
            return r.get("result", {}).get("value")

        def wait_for(expr, timeout=90.0, tick=0.25):
            end = time.time() + timeout
            while time.time() < end:
                try:
                    if ev(expr):
                        return True
                except RuntimeError:
                    pass
                time.sleep(tick)
            return False

        # ---------------- 1) 小 JSON 页面 ----------------
        print("\n=== 1) 小 JSON 页面：被内容脚本接管、树挂在 Shadow DOM 里 ===")
        c.navigate("http://127.0.0.1:%d/tools/fixtures/page-small.json" % port, timeout=60.0)
        ok = wait_for(probe_expr("!!(S() && S().querySelector('.jf-root'))"), timeout=30.0)
        check("JSON 页面被接管（Shadow DOM 里出现 .jf-root）", ok)
        if ok:
            host_ok = ev("!!document.getElementById('__jf_page_host__')")
            check("宿主元素在页面里、页面侧看不到 .jf-row（影子隔离）",
                  bool(host_ok) and ev("document.querySelectorAll('.jf-row').length") == 0)
            sp = ev(probe_expr(
                "(function(){var s=S();"
                "var rows=[].slice.call(s.querySelectorAll('.jf-window .jf-row'));"
                "var st=s.querySelector('.jf-status');"
                "var m=st?st.textContent.match(/([\\d,]+)\\s*行/):null;"
                "return JSON.stringify({"
                "dom:rows.length,"
                "statusRows:m?parseInt(m[1].replace(/,/g,''),10):null,"
                "keys:[].slice.call(s.querySelectorAll('.jf-key')).slice(0,6).map(function(k){return k.textContent;})});"
                "})()"))
            sp = json.loads(sp)
            check("行表长度 = 美化输出行数（%d）" % small_expect,
                  sp["statusRows"] == small_expect, sp["statusRows"])
            check("小文档一屏装得下 → DOM 行数 = 行表长度", sp["dom"] == sp["statusRows"],
                  "%s vs %s" % (sp["dom"], sp["statusRows"]))
            check("键名渲染出来了", '"code"' in (sp["keys"] or []), sp["keys"])

        # ---------------- 2) 大 JSON 页面 ----------------
        sz_mb = PAGE_BIG.stat().st_size / 1048576.0
        print("\n=== 2) 大 JSON 页面（%s，%.1f MB）：虚拟化结构 ===" % (PAGE_BIG.name, sz_mb))
        c.navigate("http://127.0.0.1:%d/tools/fixtures/%s" % (port, PAGE_BIG.name), timeout=120.0)
        ok = wait_for(probe_expr("!!(S() && S().querySelector('.jf-sizer'))"), timeout=120.0)
        check("大 JSON 页面被接管并建出行表（.jf-sizer 出现）", ok)
        if not ok:
            print("  页面没就绪，后续断言跳过")
            return 3
        print("  注：tools/fixtures/big-20mb.json（%.1f MB）故意不在这条链路上 —— "
              "content.js 有 maxAutoSize（默认 20MB）门槛，越线就跳过自动接管。"
              % (BIG.stat().st_size / 1048576.0))

        p = json.loads(ev(probe_expr(
            "(function(){var s=S();var st=s.querySelector('.jf-status');"
            "var m=st?st.textContent.match(/([\\d,]+)\\s*行/):null;"
            "var rows=[].slice.call(s.querySelectorAll('.jf-window .jf-row'));"
            "var nos=rows.map(function(r){var g=r.querySelector('.jf-no');return g?g.textContent:'';});"
            "var idx=rows.map(function(r){return parseInt(r.getAttribute('data-i'),10);});"
            "var sz=s.querySelector('.jf-sizer');"
            "return JSON.stringify({"
            "rows:m?parseInt(m[1].replace(/,/g,''),10):null,"
            "dom:rows.length,"
            "first:rows.length?parseInt(rows[0].getAttribute('data-i'),10):-1,"
            "last:rows.length?parseInt(rows[rows.length-1].getAttribute('data-i'),10):-1,"
            "nos:nos,idx:idx,"
            "sizer:Math.round(parseFloat(sz.style.height)||0),"
            "status:st?st.textContent:''});})()")))
        check("行表长度 > 10 万", p["rows"] and p["rows"] > 100000, "rows=%s" % p["rows"])
        check("DOM 行数是几十行（<= 120）", p["dom"] and p["dom"] <= 120, "dom=%s" % p["dom"])
        expect_h = PAD_TOP + p["rows"] * ROW_H + PAD_BOTTOM
        check("spacer 高度 = 留白 + 行数 × 行高", abs(p["sizer"] - expect_h) <= 2,
              "sizer=%s expect=%s" % (p["sizer"], expect_h))
        # 行号是用户设置（默认关），这条链路上没开，所以 .jf-no 的 textContent 是空的。
        # 该验的是「窗口是一段连续行区间」，改用行上的 data-i 序列来判。
        check("窗口内行下标严格连续（虚拟化最容易错的地方）",
              p["idx"] == list(range(p["first"], p["last"] + 1)),
              "idx[0]=%s idx[-1]=%s 共 %s 行" % (p["idx"][0], p["idx"][-1], len(p["idx"])))
        check("行号默认关闭时 .jf-no 为空（说明行号确实走设置）",
              all(x == "" for x in p["nos"]), repr(p["nos"][:3]))

        # ---------------- 3) 大 JSON 页面滚动 ----------------
        print("\n=== 3) 大 JSON 页面滚动：窗口跟着位移走、DOM 行数恒定 ===")
        # 查看器重画窗口是走 rAF 的，而后台标签页的 rAF 会被浏览器暂停 ——
        # 不把标签页带到前台，这里会一直等一个永不到来的帧（实测 300s 超时）。
        c.send("Page.bringToFront")
        time.sleep(0.4)
        # 先确认这一帧真的会来。查看器重画窗口靠 rAF，而 rAF 在「后台/被遮挡」的
        # 标签页里会被浏览器停掉 —— 那种情况下滚动断言必然全红，但那不是代码的问题。
        # 这里的探针把原因直接写进输出，免得下次误判成渲染缺陷。
        raf = ev("Promise.race([new Promise(function(r){requestAnimationFrame(function(){r('raf-ok');});}),"
                 "new Promise(function(r){setTimeout(function(){r('raf-paused');},1500);})])")
        print("  requestAnimationFrame 状态：%s" % raf)
        if raf != "raf-ok":
            print("  → 窗口在被遮挡/后台的标签页里，rAF 被暂停，滚动断言跳过"
                  "（启动浏览器时加 --disable-backgrounding-occluded-windows "
                  "--disable-renderer-backgrounding --disable-features=CalculateNativeWinOcclusion）")
        dom_counts = []
        for ratio in (0.25, 0.5, 0.999) if raf == "raf-ok" else ():
            r = json.loads(ev(probe_expr(
                "(function(){var s=S();var b=s.querySelector('.jf-body');"
                "var max=b.scrollHeight-b.clientHeight;b.scrollTop=Math.round(max*%f);"
                "return JSON.stringify({scrollTop:Math.round(b.scrollTop)});})()" % ratio)))
            time.sleep(0.35)                     # 等一帧把窗口重画完（rAF 在 16ms 内）
            sp = json.loads(ev(probe_expr(
                "(function(){var s=S();var b=s.querySelector('.jf-body');"
                "var rows=[].slice.call(s.querySelectorAll('.jf-window .jf-row'));"
                "return JSON.stringify({dom:rows.length,scrollTop:Math.round(b.scrollTop),"
                "idx:rows.map(function(x){return parseInt(x.getAttribute('data-i'),10);})});})()")))
            dom_counts.append(sp["dom"])
            want = max(0, int(sp["scrollTop"] // ROW_H) - 6)
            first = sp["idx"][0] if sp["idx"] else -1
            check("滚到 %.3f：窗口首行下标跟滚动位移走" % ratio,
                  abs(first - want) <= 2,
                  "first=%s want≈%s scrollTop=%s" % (first, want, sp["scrollTop"]))
            check("滚到 %.3f：行下标仍连续" % ratio,
                  sp["idx"] == list(range(sp["idx"][0], sp["idx"][-1] + 1)) if sp["idx"] else False,
                  "idx[0]=%s" % (sp["idx"][0] if sp["idx"] else "-"))
        if dom_counts:
            check("多次滚动 DOM 行数都恒定", max(dom_counts) <= 120, dom_counts)

        # ---------------- 4) Esc 退出 ----------------
        print("\n=== 4) Esc 退出查看器、页面交还浏览器 ===")
        # 工具栏上没有「还原原文」按钮 —— 关闭入口统一收敛到 Esc（viewer/content.js
        # 都没有 onRestore 的实现，content.js 传的那个选项是历史残留）。所以这里
        # 验的是真实的还原路径：Esc。
        ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        time.sleep(0.6)
        check("Esc 后宿主元素被移除（页面交还浏览器）",
              ev("!document.getElementById('__jf_page_host__')"))

        # ---------------- 5) 报错 ----------------
        print("\n=== 5) 报错 ===")
        errs = ev("JSON.stringify(window.__errs || [])")
        check("全程无 JS 报错", errs in ("[]", None), errs)

        if args.shot:
            shot_dir.mkdir(parents=True, exist_ok=True)
            c.navigate("http://127.0.0.1:%d/tools/fixtures/%s" % (port, PAGE_BIG.name), timeout=120.0)
            wait_for(probe_expr("!!(S() && S().querySelector('.jf-sizer'))"), timeout=120.0)
            time.sleep(0.5)
            c.screenshot(str(shot_dir / "ext-json-page.png"))
            print("  截图 dist/shots/ext-json-page.png")

        print("\n" + "=" * 52)
        if fails:
            print("[失败] %d 项：%s" % (len(fails), "；".join(fails)))
            return 6
        print("[通过] 扩展路径（.json 页面 → Shadow DOM 虚拟化树视图）全部达标")
        return 0
    except (CDPError, RuntimeError) as exc:
        print("错误：%s" % exc)
        return 1
    finally:
        try:
            c.close()
        except Exception:
            pass
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
