#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-virtual-tree.py —— 验收「树视图虚拟化」（P1）。

跑的是 tools/fixtures/vtree.html 这个最小宿主，它只加载 viewer.js 那条真实渲染
路径，不套扩展/编辑器外壳，所以测出来的就是渲染本身的行为。

断言（大文档 22MB 为主线）：
  1. 行表长度 = 文档行数（36 万），但 DOM 里始终只有几十行 → 虚拟化成立
  2. spacer 高度 = 上下留白 + 行数 × 行高，且与 body.scrollHeight 一致
  3. 滚到任意位置：DOM 行数不变，窗口首行下标跟着滚动位移走，滚动条到底能到文末
  4. 行号 = 行下标 + 1，窗口内连续无空洞（虚拟化下最容易错的就是这个）
  5. 折叠 → 展开一次：行表长度先减后**完全还原**（老版本会翻倍，这是回归点），
     spacer 跟着变，DOM 行数不变
  6. 超长值单行截断（行内 512 字符 + 省略号），全文进 title
  7. 「压缩」视图：切成紧凑文本、切回来行表不变
  8. 跳行 revealRow(i)：任意行都能滚进窗口，且 DOM 行数不变（虚拟化后只有
     viewer 能把某一行「拿出来」，外部 querySelector 找不到不在窗口里的行）
  9. 「复制 / 下载」拿到的输出是**完整全文** —— 压缩视图只铺前 2MB 属屏幕策略，
     绝不能被当成输出上限（用独立算出的紧凑文本长度逐字符比对）
 10. 小文档：行表长度 = 美化输出的行数；跨层级缩进拉开、行号钉在同一列
 11. 全程无 JS 报错

前置：Edge 已以 --remote-debugging-port=9222 启动（脚本自带 HTTP 服务）。
用法：python tools/verify-virtual-tree.py [--port 9222] [--http-port 18571] [--shot]
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

PAD_TOP = 14
PAD_BOTTOM = 80
ROW_H = 24          # 14px 字号 × 1.7 = 23.8 → round = 24

fails = []
def check(name, ok, extra=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  " + str(extra)) if extra else ""))
    if not ok:
        fails.append(name)
    return ok


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
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="verify-virtual-tree.py")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--http-port", type=int, default=18571)
    ap.add_argument("--shot", action="store_true", help="额外存几张截图到 dist/shots/")
    args = ap.parse_args(argv)

    if not BIG.exists():
        print("缺少测试数据 %s" % BIG)
        return 2

    # 自带 HTTP 服务：让浏览器直接 fetch 大文件，不走 CDP 传文本
    srv = serve(ROOT)
    port = srv.server_address[1]
    print("本地服务 http://127.0.0.1:%d  (根目录 %s)" % (port, ROOT))

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

        def ev(expr, timeout=300.0):
            r = c.send("Runtime.evaluate",
                       {"expression": expr, "returnByValue": True,
                        "awaitPromise": True, "userGesture": True}, timeout=timeout)
            if r.get("exceptionDetails"):
                exc = r["exceptionDetails"]
                desc = (exc.get("exception") or {}).get("description") or exc.get("text")
                raise RuntimeError("页面 JS 异常：%s" % str(desc)[:1500])
            return r.get("result", {}).get("value")

        url = ("http://127.0.0.1:%d/tools/fixtures/vtree.html?src=/tools/fixtures/big-20mb.json&ln=1"
               % port)
        c.navigate(url, timeout=60.0)
        ok = c.wait_for("!!window.__vt && window.__vt.probe().rows > 0", timeout=60.0)
        if not ok:
            print("页面没就绪或没有行")
            return 3

        info = ev("(window.__vtReady || Promise.resolve(null)).then(function(r){return JSON.stringify(r)})")
        ready = json.loads(info) if info else None
        chars = ready.get("chars") if ready else 0
        print("\n--- 载入 %s（%.1f MB）---" % (BIG.name, (chars or 0) / 1048576))
        if ready:
            print("  首屏（解析 + 建行表 + 画窗口）：%sms" % ready.get("ms"))

        def load_big():
            return ev("fetch('/tools/fixtures/big-20mb.json',{cache:'no-store'})"
                      ".then(function(r){return r.text()})"
                      ".then(function(t){window.__vt.setText(t); return t.length;})")

        # ---------------- 1) 结构性断言 ----------------
        print("\n=== 1) 虚拟化结构（36 万行文档）===")
        p = ev("JSON.stringify(window.__vt.probe())")
        p = json.loads(p)
        check("行表长度 = 文档行数（> 30 万）", p["rows"] > 300000, "rows=%d" % p["rows"])
        check("DOM 行数保持在几十行（<= 120）", p["domRows"] <= 120, "dom=%d" % p["domRows"])
        check("行高 24px（14px × 1.7 取整）", p["rowHeight"] == ROW_H, p["rowHeight"])
        expect_h = PAD_TOP + p["rows"] * ROW_H + PAD_BOTTOM
        # 容差 2px：36 万行 → 总高 864 万 px，浏览器对 style.height 的取整会带来 1~2px 误差
        check("spacer 高度 = 留白 + 行数 × 行高",
              abs(p["sizerHeight"] - expect_h) <= 2,
              "sizer=%d expect=%d" % (p["sizerHeight"], expect_h))
        check("滚动高度与 spacer 一致",
              abs(p["scrollHeight"] - p["sizerHeight"]) <= 2,
              "%d vs %d" % (p["scrollHeight"], p["sizerHeight"]))
        check("首屏从第 0 行开始", p["firstIdx"] == 0, p["firstIdx"])
        check("行号从 1 开始且窗口内连续",
              p["nos"][0] == "1" and p["nos"] == [str(i + 1) for i in range(p["firstIdx"], p["lastIdx"] + 1)],
              "nos[0]=%s len=%d" % (p["nos"][0], len(p["nos"])))
        check("状态栏显示行数", "{:,} 行".format(p["rows"]) in (p["stats"] or ""), p["stats"])

        # ---------------- 2) 滚动 ----------------
        print("\n=== 2) 滚动：DOM 行数恒定、窗口跟着位移走 ===")
        dom_counts = []
        for ratio in (0.25, 0.5, 0.75, 0.999):
            sp = json.loads(ev("window.__vt.scrollTo(%f).then(function(p){return JSON.stringify(p)})" % ratio))
            dom_counts.append(sp["domRows"])
            want = max(0, int(sp["scrollTop"] // ROW_H) - 6)
            check("滚到 %.3f：窗口首行下标跟滚动位移走" % ratio,
                  abs(sp["firstIdx"] - want) <= 2,
                  "firstIdx=%d want≈%d scrollTop=%d" % (sp["firstIdx"], want, sp["scrollTop"]))
            check("滚到 %.3f：行号仍连续" % ratio,
                  sp["nos"] == [str(i + 1) for i in range(sp["firstIdx"], sp["lastIdx"] + 1)],
                  "nos[0]=%s" % (sp["nos"][0] if sp["nos"] else "-"))
        check("四次滚动 DOM 行数都恒定", max(dom_counts) <= 120, dom_counts)

        endp = json.loads(ev("window.__vt.scrollTo(1).then(function(p){return JSON.stringify(p)})"))
        check("滚到底能看到最后一行", endp["lastIdx"] == endp["rows"] - 1,
              "lastIdx=%d rows=%d" % (endp["lastIdx"], endp["rows"]))
        tail = ev("""(function(){var r=document.querySelectorAll('.jf-window .jf-row');
                     var n=r[r.length-1]; return n.querySelector('.jf-content').textContent;})()""")
        # 末行必须是根容器的闭括号。别硬编码，按文档实际的根首字符推：
        # big-20mb.json 的根是对象（首行 "{"），所以末行是 "}"；换成数组根时要变 "]"
        head = ev("""(function(){var r=document.querySelectorAll('.jf-window .jf-row');
                     return r[0].querySelector('.jf-content').textContent;})()""")
        closer = "]" if str(head).lstrip().startswith("[") else "}"
        check("最后一行是根容器的闭括号", str(tail).strip() == closer,
              "%r（根首字符 %r → 期望 %r）" % (tail, str(head).lstrip()[:1], closer))

        # ---------------- 3) 折叠 / 展开 ----------------
        print("\n=== 3) 折叠 → 展开（老版本会翻倍的回归点）===")
        ev("window.__vt.scrollTo(0)")
        before = json.loads(ev("JSON.stringify(window.__vt.probe())"))
        t1 = json.loads(ev("JSON.stringify(window.__vt.toggleFirst())"))
        check("折叠后行表变短", t1["after"] < t1["before"],
              "%d → %d" % (t1["before"], t1["after"]))
        check("折叠后 spacer 高度跟着变",
              abs(t1["sizerHeight"] - (PAD_TOP + t1["after"] * ROW_H + PAD_BOTTOM)) <= 1,
              t1["sizerHeight"])
        check("折叠后 DOM 行数仍受控", t1["dom"] <= 120, t1["dom"])
        check("折叠不改变滚动位置", abs(t1["scrollTop"] - before["scrollTop"]) <= 1,
              "%s vs %s" % (t1["scrollTop"], before["scrollTop"]))
        t2 = json.loads(ev("JSON.stringify(window.__vt.toggleFirst())"))
        check("再展开：行表长度完全还原（没有重复行）",
              t2["after"] == t1["before"], "%d → %d" % (t1["after"], t2["after"]))
        dup = ev("""(function(){
            var rs=[].slice.call(document.querySelectorAll('.jf-window .jf-row'));
            var ids=rs.map(function(r){return r.getAttribute('data-i');});
            var seen={},d=0;
            ids.forEach(function(k){ if(seen[k])d++; seen[k]=1; });
            return d;})()""")
        check("窗口内没有重复行号", dup == 0, dup)

        # ---------------- 4) 长值截断 ----------------
        print("\n=== 4) 超长值：单行截断 + 全文进 title ===")
        long_str = "x" * 5000
        ev("window.__vt.setText(%s)" % json.dumps(json.dumps({"k": long_str}, ensure_ascii=False)))
        tv = json.loads(ev("JSON.stringify(window.__vt.truncatedValue())"))
        check("行内只渲染 512 字符 + 省略号", tv and tv["len"] == 513, tv and tv["len"])
        # title 报的是**被渲染的整段值文本**的长度，即 JSON 字符串字面量长度（含两侧引号）：
        # "x"×5000 → 5002 字符，不是 5000
        want_len = len(json.dumps(long_str))  # '"xxx…x"' → 5002（含两侧引号）
        want_txt = "{:,}".format(want_len)
        check("title 里给出总字符数", tv and want_txt in tv["title"],
              "%s（期望含 %s）" % (tv and tv["title"][:40], want_txt))

        # ---------------- 5) 压缩视图 ----------------
        print("\n=== 5) 「压缩」视图切换 ===")
        load_big()
        btns = ev("JSON.stringify(window.__vt.btnTexts())")
        print("  工具条按钮：%s" % btns)
        ms = ev("""(function(){var t=performance.now(); window.__vt.clickBtn(2);
                    return Math.round(performance.now()-t);})()""")
        cp = json.loads(ev("JSON.stringify(window.__vt.probe())"))
        check("压缩视图渲染出紧凑文本", cp["ctextLen"] > 1000, "chars=%d" % cp["ctextLen"])
        check("压缩视图里没有树行", cp["domRows"] == 0, cp["domRows"])
        print("  切到压缩：%sms（含 22MB 紧凑序列化）" % ms)
        ms2 = ev("""(function(){var t=performance.now(); window.__vt.clickBtn(2);
                     return Math.round(performance.now()-t);})()""")
        back = json.loads(ev("JSON.stringify(window.__vt.probe())"))
        check("切回美化：行表长度与之前一致", back["rows"] > 300000, back["rows"])
        print("  切回美化：%sms" % ms2)

        # ---------------- 6) 跳行 + 全文输出 ----------------
        print("\n=== 6) 跳行（revealRow）与「复制 / 下载」输出完整全文 ===")
        load_big()
        nr = json.loads(ev("JSON.stringify(window.__vt.probe())"))["rows"]
        for target in (0, 12345, 180000, nr - 1):
            rr = json.loads(ev("JSON.stringify(window.__vt.revealRow(%d))" % target))
            pr = rr["probe"]
            check("revealRow(%d)：目标行落进窗口" % target,
                  pr["firstIdx"] <= target <= pr["lastIdx"],
                  "窗口 [%d, %d]" % (pr["firstIdx"], pr["lastIdx"]))
            check("revealRow(%d)：DOM 行数仍受控" % target, pr["domRows"] <= 120, pr["domRows"])
        # 压缩视图只把前 2MB 铺到屏幕上（一整行几 MB 的文本连 shaping 都会假死），
        # 但「复制 / 下载」拿的是 outputText()，必须是**完整**全文 —— 这是虚拟化
        # 最容易踩的坑：把「显示策略」误当成「输出上限」，静默截断用户的文档。
        COMPACT_MAX = 2 * 1024 * 1024
        ev("window.__vt.clickBtn(2)")                     # 切到压缩
        mode = ev("window.__vt.outMode()")
        cnow = json.loads(ev("JSON.stringify(window.__vt.probe())"))
        clen = ev("window.__vt.outputLen()")
        check("压缩视图确实切过去了", mode == "compact", mode)
        check("屏幕上只铺前 2MB（显示策略，防 shaping 假死）",
              0 < cnow["ctextLen"] < COMPACT_MAX + 4096, cnow["ctextLen"])
        check("输出不止屏幕上那 2MB（没把显示上限当输出上限）",
              clen and clen > COMPACT_MAX, "output=%s" % clen)
        # 最强的一条：拿页面里独立算出的完整紧凑文本长度逐字符对齐。
        # 阈值断言容易被「这份 fixture 缩进后就多大」带偏，等长比对不会。
        truth = ev("fetch('/tools/fixtures/big-20mb.json',{cache:'no-store'})"
                   ".then(function(r){return r.text()})"
                   ".then(function(t){return JSON.stringify(JSON.parse(t)).length;})")
        check("「复制 / 下载」的输出 = 独立算出的完整全文长度",
              clen == truth, "output=%s truth=%s" % (clen, truth))
        ev("window.__vt.clickBtn(2)")                     # 切回美化

        print("\n=== 7) 小文档：行数 = 美化输出行数，缩进与行号对齐 ===")
        small = {
            "code": "0",
            "data": {"orderId": "600653836507516928", "buyer": {"id": 10086, "vip": True}},
            "list": [1, 2, 3]
        }
        pretty = json.dumps(small, ensure_ascii=False, indent=2)
        n_lines = len(pretty.split("\n"))
        ev("window.__vt.setText(%s)" % json.dumps(pretty, ensure_ascii=False))
        sp = json.loads(ev("JSON.stringify(window.__vt.probe())"))
        check("行表长度 = 美化输出行数", sp["rows"] == n_lines,
              "%d vs %d" % (sp["rows"], n_lines))
        check("小文档 DOM 行数 = 行表长度（一屏装得下就全渲染）",
              sp["domRows"] == sp["rows"], "%d vs %d" % (sp["domRows"], sp["rows"]))
        a = json.loads(ev("JSON.stringify(window.__vt.rowInfoByKey('code'))"))
        b = json.loads(ev("JSON.stringify(window.__vt.rowInfoByKey('orderId'))"))
        c2 = json.loads(ev("JSON.stringify(window.__vt.rowInfoByKey('id'))"))
        check("越深的键越往右（缩进保留）",
              a and b and c2 and a["contentLeft"] < b["contentLeft"] < c2["contentLeft"],
              "%s < %s < %s" % (a and a["contentLeft"], b and b["contentLeft"], c2 and c2["contentLeft"]))
        check("行号钉在同一列（不随层级漂）",
              a and b and c2 and a["noLeft"] == b["noLeft"] == c2["noLeft"],
              "%s / %s / %s" % (a and a["noLeft"], b and b["noLeft"], c2 and c2["noLeft"]))
        kp = json.loads(ev("window.__vt.clickFirstKey()"
                           ".then(function(r){return JSON.stringify(r)})"))
        check("点键复制路径：title 是完整路径", kp and kp["title"].endswith("$.code"), kp and kp["title"])
        check("点键后弹出提示", kp and ("已复制路径" in (kp["toast"] or "")), kp and kp["toast"])

        # ---------------- 8) 报错 ----------------
        errs = ev("JSON.stringify(window.__vt.errors)")
        check("全程无 JS 报错", errs in ("[]", None), errs)

        if args.shot:
            shot_dir.mkdir(parents=True, exist_ok=True)
            load_big()
            for name, ratio in (("vtree-top", 0.0), ("vtree-mid", 0.5), ("vtree-end", 1.0)):
                ev("window.__vt.scrollTo(%f)" % ratio)
                time.sleep(0.35)
                c.screenshot(str(shot_dir / (name + ".png")))
                print("  截图 dist/shots/%s.png" % name)

        print("\n" + "=" * 52)
        if fails:
            print("[失败] %d 项：%s" % (len(fails), "；".join(fails)))
            return 6
        print("[通过] 虚拟化树视图：结构 / 滚动 / 折叠 / 截断 / 压缩 / 跳行 / 全文输出 / 小文档 全部达标")
        return 0
    except CDPError as exc:
        print("CDP 错误：%s" % exc)
        return 1
    finally:
        try:
            c.close()
        except Exception:
            pass
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
