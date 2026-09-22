#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-ext-116.py —— 对**已加载到浏览器里的扩展**（dist/unpacked）做上线前验收。

v1.1.6 的核心变化是「大文档走 CodeMirror 6 虚拟化视图」，所以本脚本的重点是
把这条路径在真实扩展环境里钉死，而不是只信模块级测试：

  1. 扩展已加载 + service worker 就位
  2. JSON 接口被内容脚本自动接管（小文档仍走树视图）            ← 不能回归
  3. 折叠 → 展开 ×3：行数不增长、无重复元素、行号连续            ← 不能回归
  4. 编辑页小 JSON：树视图 + 大整数不丢精度                      ← 不能回归
  5. 11MB 粘贴 → 大文档视图：完整行数、虚拟化（DOM 行数极少）、无「加载更多」
  6. 22MB 粘贴 → **自动**格式化（旧版只会给「内容过大」）
  7. 字符串外大整数 → 走保真路径，20 位整数原样出现在渲染结果里
  8. 切深色主题 → 大文档视图宿主跟着换 token
  9. 全流程无 JS 报错

用法：
    python tools/verify-ext-116.py [--port 9333] [--http-port 18555]
"""

import argparse
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient, CDPError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BIG_FIXTURE = ROOT / "tools" / "fixtures" / "big-20mb.json"
MENU_FIXTURE = ROOT / "tools" / "fixtures" / "big-menu.json"

# 夹在字符串外的 20 位大整数：超出 2^53，JSON.parse 一过就丢精度，
# 所以 hasRawRisk 会命中、排版必须走保真扫描路径
BIG_ID = "12345678901234567890"
RISK_KEY = '"__bigId__": ' + BIG_ID

SAMPLE = {
    "code": "0",
    "msg": "success",
    "data": {
        "orderId": "600653836507516928",
        "amount": 128.5,
        "paid": True,
        "tags": ["vip", "2026-09"],
        "buyer": {"id": 10086, "nickname": "张三"},
        "items": [{"sku": "A-1", "qty": 2}, {"sku": "B-7", "qty": 1}],
    },
}

ERROR_HOOK = """
window.__errs = [];
window.addEventListener('error', function (e) { window.__errs.push('error: ' + (e.message || e.type)); });
window.addEventListener('unhandledrejection', function (e) {
  window.__errs.push('rejection: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason)));
});
"""


def _risk_variant(text):
    """把夹具改成「第一个键是字符串外的 20 位大整数」，强制走保真路径。

    只是往开头插一行，JSON 依然合法；行数 +1（排版会把它单独放一行）。
    """
    assert text.lstrip().startswith("{")
    i = text.index("{")
    return text[: i + 1] + "\n  " + RISK_KEY + "," + text[i + 1:]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send_bytes(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path.startswith("/api/order"):
            self._json(SAMPLE)
        elif self.path.startswith("/api/risk"):
            text = MENU_FIXTURE.read_text(encoding="utf-8")
            self._send_bytes(_risk_variant(text).encode("utf-8"))
        elif self.path.startswith("/api/menu"):
            self._send_bytes(MENU_FIXTURE.read_bytes())
        elif self.path.startswith("/api/big"):
            self._send_bytes(BIG_FIXTURE.read_bytes())
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def start_server(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def unpacked_extension_id(path):
    """本地加载（未打包）扩展的 ID = sha256(绝对路径的 UTF-16LE) 前 16 字节，nibble 映射 a..p。

    MV3 的 service worker 空闲后会被回收，/json/list 里就没这条 target 了；
    用路径反推是确定性的，不依赖 SW 是否活着。（Windows 上必须 UTF-16LE。）
    """
    import hashlib
    h = hashlib.sha256(str(path).encode("utf-16-le")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in h)


def find_extension_id(client, ext_dir=None):
    for t in client.targets():
        u = t.get("url") or ""
        if u.startswith("chrome-extension://") and u.endswith("/src/background/service-worker.js"):
            return u.split("/")[2]
    if ext_dir:
        return unpacked_extension_id(ext_dir)
    return None


def ev(client, expr, timeout=300.0):
    """evaluate 的 awaitPromise 版：本脚本大量使用 async IIFE，
    而 CDPClient.evaluate 固定 awaitPromise=False，拿到的是 Promise 而不是值。"""
    res = client.send(
        "Runtime.evaluate",
        {"expression": expr, "returnByValue": True, "awaitPromise": True, "userGesture": True},
        timeout=timeout,
    )
    if res.get("exceptionDetails"):
        exc = res["exceptionDetails"]
        desc = (exc.get("exception") or {}).get("description") or exc.get("text")
        raise CDPError("页面 JS 异常：%s" % str(desc)[:1500])
    return res.get("result", {}).get("value")


# 页面接管后，查看器挂在 #__jf_page_host__ 的 Shadow DOM 里（mode:'open'），
# document.querySelector 穿不透，必须经 shadowRoot 取。
JF_ROOT = (
    "function __jfRoot(){var h=document.getElementById('__jf_page_host__');"
    "return (h&&h.shadowRoot)?h.shadowRoot.querySelector('.jf-root'):null;}"
)


def expected_lines(p):
    t = p.read_text(encoding="utf-8")
    return t.count("\n") + (0 if t.endswith("\n") else 1)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9333, help="CDP 调试端口")
    ap.add_argument("--http-port", type=int, default=18555, help="本地 JSON 服务端口")
    ap.add_argument("--ext-dir", default=str(ROOT / "dist" / "unpacked"),
                    help="未打包扩展目录（SW 已回收时用它反推扩展 ID）")
    ap.add_argument("--shot", help="截图保存路径")
    args = ap.parse_args()

    base = "http://127.0.0.1:%d" % args.http_port
    srv = start_server(args.http_port)
    fails = []

    def check(name, cond, extra=""):
        print("  [%s] %-38s %s" % ("PASS" if cond else "FAIL", name, extra))
        if not cond:
            fails.append(name)

    menu_lines = expected_lines(MENU_FIXTURE)
    big_lines = expected_lines(BIG_FIXTURE)
    risk_lines = menu_lines + 1  # 注入的那一行

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=60)
    try:
        if not client.is_alive():
            print("CDP 无响应：端口 %d" % args.port, file=sys.stderr)
            return 2

        ext_id = find_extension_id(client, args.ext_dir)
        check("扩展已加载（service worker 就位）", bool(ext_id), "ID=%s" % ext_id)
        if not ext_id:
            return 3

        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_HOOK})
        client.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 940, "deviceScaleFactor": 1, "mobile": False},
        )

        # ---------- 1) 内容脚本自动接管（小文档仍走树视图） ----------
        print("\n=== 1) JSON 接口自动接管（树视图不能回归）===")
        ok = client.navigate(base + "/api/order", timeout=30)
        check("页面加载", ok)
        time.sleep(2.2)
        r1 = json.loads(ev(client,
            "(function(){" + JF_ROOT +
            "var v=__jfRoot();"
            "return JSON.stringify({takenOver:!!v,"
            "host:!!document.getElementById('__jf_page_host__'),"
            "rows: v?v.querySelectorAll('.jf-row').length:0,"
            "toolbar: v?!!v.querySelector('.jf-toolbar'):false,"
            "errs: window.__errs||[]});})()"
        ) or "{}")
        check("内容脚本接管页面", r1.get("takenOver"), "rows=%s" % r1.get("rows"))
        check("查看器工具栏存在", r1.get("toolbar"))
        check("接管过程无 JS 报错", not r1.get("errs"), str(r1.get("errs"))[:160])

        # ---------- 2) 折叠 → 展开 ×3：不得重复追加 ----------
        print("\n=== 2) 折叠再展开（P0 回归项）===")
        r2 = json.loads(ev(client, (
            "(async function(){"
            + JF_ROOT +
            """
          function snap(){
            var v=__jfRoot();
            var rows=[].slice.call(v.querySelectorAll('.jf-row'));
            var keys=rows.map(function(r){var k=r.querySelector('.jf-key');return k?k.textContent:'';}).join('|');
            var nos=[].slice.call(v.querySelectorAll('.jf-no'));
            var emptyNos=0, breaks=0, prev=null;
            for(var i=0;i<nos.length;i++){
              var t=(nos[i].textContent||'').trim();
              if(!t){emptyNos++;continue;}
              var n=parseInt(t,10);
              if(isNaN(n)) continue;
              if(prev!==null && n!==prev+1) breaks++;
              prev=n;
            }
            return {rows:rows.length, keys:keys, emptyNos:emptyNos, breaks:breaks};
          }
          function toggleFirst(){
            var v=__jfRoot();
            var t=v.querySelector('.jf-toggle');
            if(!t) return false;
            t.click();
            return true;
          }
          var before=snap();
          var after=[];
          for(var i=0;i<3;i++){
            toggleFirst();
            await new Promise(function(r){setTimeout(r,260);});
            toggleFirst();
            await new Promise(function(r){setTimeout(r,420);});
            after.push(snap());
          }
          var final=snap();
          return JSON.stringify({
            before:before, after:after, final:final,
            grew: final.rows>before.rows,
            rowsStable: after.every(function(s){return s.rows===after[0].rows;}),
            keysStable: after.every(function(s){return s.keys===after[0].keys;}),
            errs: window.__errs||[]
          });
        })()
        """
        )) or "{}")
        for i, s in enumerate(r2.get("after") or []):
            print("     第 %d 轮：rows=%s keys=%s emptyNos=%s breaks=%s"
                  % (i + 1, s.get("rows"), len((s.get("keys") or "").split("|")),
                     s.get("emptyNos"), s.get("breaks")))
        print("     基线：rows=%s" % (r2.get("before") or {}).get("rows"))
        check("展开后行数未增长", not r2.get("grew"),
              "基线 %s → 终态 %s" % ((r2.get("before") or {}).get("rows"),
                                     (r2.get("final") or {}).get("rows")))
        check("三轮展开行数一致", r2.get("rowsStable"))
        check("三轮展开键序列一致（无重复追加）", r2.get("keysStable"))
        check("行号连续无断档", ((r2.get("final") or {}).get("breaks") == 0))
        fin = r2.get("final") or {}
        if (fin.get("emptyNos") or 0) < (fin.get("rows") or 0):
            check("行号无空缺", fin.get("emptyNos") == 0, "empty=%s" % fin.get("emptyNos"))
        else:
            print("  [INFO] 行号设置默认关闭，跳过「行号无空缺」断言")
        check("折叠展开无 JS 报错", not r2.get("errs"), str(r2.get("errs"))[:160])
        if args.shot:
            client.screenshot(args.shot)
            print("     截图:", args.shot)

        # ---------- 3) 编辑页：小 JSON 仍走树视图 ----------
        print("\n=== 3) 编辑页小 JSON（树视图不能回归）===")
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30)
        client.wait_for("document.readyState==='complete' && !!document.getElementById('input')",
                        timeout=15)
        time.sleep(0.8)
        r3 = json.loads(ev(client, r"""
            (async function(){
              window.__errs=[];
              var el=document.getElementById('input');
              var host=document.getElementById('viewer');
              el.value='{"a":1,"b":[true,null,"x"],"c":{"d":600653836507516928}}';
              el.dispatchEvent(new InputEvent('input',{inputType:'insertFromPaste',bubbles:true}));
              await new Promise(function(r){setTimeout(r,900);});
              return JSON.stringify({
                rows: host.querySelectorAll('.jf-row').length,
                viewerHidden: host.hidden,
                bigHidden: document.getElementById('bigView').hidden,
                pill: document.getElementById('pillText').textContent,
                errs: window.__errs||[]
              });
            })()
        """) or "{}")
        check("小 JSON 走树视图", (r3.get("rows") or 0) > 3, "rows=%s" % r3.get("rows"))
        check("小 JSON 未误用大文档视图", r3.get("bigHidden") is True, "bigHidden=%s" % r3.get("bigHidden"))
        check("小 JSON 格式化成功", "成功" in (r3.get("pill") or ""), str(r3.get("pill")))
        check("字符串内大整数未丢精度",
              bool(client.evaluate(
                  "(document.getElementById('viewer').innerText||'').indexOf('600653836507516928')>=0"
              ).get("value")))
        check("编辑页无 JS 报错", not r3.get("errs"), str(r3.get("errs"))[:160])

        # ---------- 4~7) 大文档视图 ----------
        # 走真实粘贴路径：编辑器会拦截粘贴、把大文本放内存源，不写回 textarea
        BIG_PROBE = r"""
            (async function(){
              window.__errs=[];
              var iEl=document.getElementById('input');
              var big=document.getElementById('bigView');
              var tree=document.getElementById('viewer');
              var res=await fetch('http://127.0.0.1:__HTTP_PORT__/api/__WHICH__');
              var text=await res.text();
              var t0=performance.now();
              var dt=new DataTransfer();
              dt.setData('text/plain', text);
              document.dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:dt,bubbles:true,cancelable:true}));
              var tFirst=null;
              for(var k=0;k<400;k++){
                await new Promise(function(r){setTimeout(r,50);});
                if(big.querySelector('.cm-line')){ tFirst=performance.now()-t0; break; }
              }
              await new Promise(function(r){setTimeout(r,600);});
              var msg=(document.getElementById('msg')||{}).textContent||'';
              var m=msg.match(/([\d,]+)\s*行/);
              var lines=m?parseInt(m[1].replace(/,/g,''),10):0;
              var domRows=big.querySelectorAll('.cm-line').length;
              // 顶部渲染出来的几行：保真路径注入的大整数就在第 2 行，
              // 必须趁「还没滚动」时取下来
              function head(){
                var ls=[].slice.call(big.querySelectorAll('.cm-line')).slice(0,4);
                return ls.map(function(e){return e.textContent;}).join('\\n');
              }
              var topText=head();
              // 虚拟化验证：滚到很后面，渲染出来的行应该换了一批
              var sc=big.querySelector('.cm-scroller');
              var sigBefore=head();
              if(sc) sc.scrollTop=120000;
              await new Promise(function(r){setTimeout(r,500);});
              var st1=sc?Math.round(sc.scrollTop):-1;
              var sigAfter=head();
              if(sc) sc.scrollTop=0;
              await new Promise(function(r){setTimeout(r,500);});
              var sigBack=head();
              return JSON.stringify({
                chars:text.length,
                visible: !big.hidden,
                treeHidden: tree.hidden,
                hasCM: !!big.querySelector('.cm-editor'),
                hasGutter: !!big.querySelector('.cm-gutters'),
                lines: lines,
                domRows: domRows,
                topText: topText,
                scrollTop: st1,
                sigChanged: sigAfter!==sigBefore,
                sigRestored: sigBack===sigBefore,
                hasLoadMore: !!big.querySelector('.jf-summary') ||
                             !!(tree.querySelector && tree.querySelector('.jf-summary')),
                pill: document.getElementById('pillText').textContent,
                msg: msg,
                ms: Math.round(tFirst===null?-1:tFirst),
                errs: window.__errs||[]
              });
            })()
        """

        def big_case(which):
            return (BIG_PROBE.replace("__HTTP_PORT__", str(args.http_port))
                              .replace("__WHICH__", which))

        def open_editor():
            client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30)
            client.wait_for("document.readyState==='complete' && !!document.getElementById('input')",
                            timeout=15)
            time.sleep(0.9)

        print("\n=== 4) 11MB 粘贴 → 大文档视图（完整行数 + 虚拟化）===")
        open_editor()
        r4 = json.loads(ev(client, big_case("menu")) or "{}")
        print("     字符=%s 首帧=%sms 报告行数=%s DOM行数=%s 胶囊=%s"
              % (r4.get("chars"), r4.get("ms"), r4.get("lines"), r4.get("domRows"), r4.get("pill")))
        print("     文案=%s" % (r4.get("msg") or "")[:100])
        check("大文档视图已显示", r4.get("visible"), "visible=%s" % r4.get("visible"))
        check("树视图已让位", r4.get("treeHidden"), "treeHidden=%s" % r4.get("treeHidden"))
        check("CodeMirror 已挂载", r4.get("hasCM") and r4.get("hasGutter"))
        check("格式化成功", "成功" in (r4.get("pill") or ""), str(r4.get("pill")))
        check("行数 = 完整行数（不再截断）", r4.get("lines") == menu_lines,
              "报告 %s / 期望 %s" % (r4.get("lines"), menu_lines))
        check("虚拟化：DOM 行数远小于总行数",
              (r4.get("domRows") or 0) > 0 and (r4.get("domRows") or 0) < 400,
              "DOM %s / 总 %s" % (r4.get("domRows"), r4.get("lines")))
        check("已无「加载更多」哨兵", not r4.get("hasLoadMore"))
        check("滚动后渲染内容是另一批行", r4.get("sigChanged") and (r4.get("scrollTop") or 0) > 0,
              "scrollTop=%s" % r4.get("scrollTop"))
        check("滚回顶部后内容复原（确属虚拟化重绘）", r4.get("sigRestored"))
        check("11MB 无 JS 报错", not r4.get("errs"), str(r4.get("errs"))[:200])

        print("\n=== 5) 22MB 粘贴 → 自动格式化（旧版只会给「内容过大」）===")
        open_editor()
        r5 = json.loads(ev(client, big_case("big")) or "{}")
        print("     字符=%s 首帧=%sms 报告行数=%s DOM行数=%s"
              % (r5.get("chars"), r5.get("ms"), r5.get("lines"), r5.get("domRows")))
        check("22MB 未再提示「内容过大」", "内容过大" not in (r5.get("pill") or "") + (r5.get("msg") or ""),
              str(r5.get("pill")))
        check("22MB 自动格式化成功", "成功" in (r5.get("pill") or ""), str(r5.get("pill")))
        check("22MB 行数 = 完整行数", r5.get("lines") == big_lines,
              "报告 %s / 期望 %s" % (r5.get("lines"), big_lines))
        check("22MB 首帧在 15s 内", (r5.get("ms") or -1) >= 0 and (r5.get("ms") or 1e9) < 15000,
              "%sms" % r5.get("ms"))
        check("22MB 无 JS 报错", not r5.get("errs"), str(r5.get("errs"))[:200])

        print("\n=== 6) 字符串外大整数 → 走保真路径，20 位整数原样保留 ===")
        open_editor()
        r6 = json.loads(ev(client, big_case("risk")) or "{}")
        print("     字符=%s 报告行数=%s 胶囊=%s" % (r6.get("chars"), r6.get("lines"), r6.get("pill")))
        print("     顶部渲染内容=%r" % (r6.get("topText") or "")[:120])
        check("命中保真路径（胶囊注明原文保真）", "保真" in (r6.get("pill") or ""), str(r6.get("pill")))
        check("保真路径行数 = 完整行数", r6.get("lines") == risk_lines,
              "报告 %s / 期望 %s" % (r6.get("lines"), risk_lines))
        # 大整数在原文件第 2 行，渲染出来就该一字不差（走原生 parse 会变成 12345678901234567000）
        check("20 位大整数原样出现在渲染结果里",
              BIG_ID in (r6.get("topText") or ""),
              (r6.get("topText") or "")[:160])
        check("保真路径无 JS 报错", not r6.get("errs"), str(r6.get("errs"))[:200])

        print("\n=== 7) 切深色主题 → 大文档视图跟着换 token ===")
        open_editor()
        ev(client, big_case("menu"))
        r7 = json.loads(ev(client, r"""
            (async function(){
              var big=document.getElementById('bigView');
              function bg(){ return getComputedStyle(big).backgroundColor; }
              var before=bg();
              await new Promise(function(res){ chrome.storage.sync.set({theme:'dark'}, res); });
              await new Promise(function(r){setTimeout(r,700);});
              var darkTheme=big.getAttribute('data-theme');
              var after=bg();
              var editorBg=getComputedStyle(big.querySelector('.cm-editor')).backgroundColor;
              await new Promise(function(res){ chrome.storage.sync.set({theme:'light'}, res); });
              await new Promise(function(r){setTimeout(r,600);});
              return JSON.stringify({before:before, after:after, darkTheme:darkTheme,
                                     editorBg:editorBg, back:bg(),
                                     errs: window.__errs||[]});
            })()
        """) or "{}")
        print("     浅色 bg=%s → 深色 bg=%s（编辑器 %s）→ 复位 %s"
              % (r7.get("before"), r7.get("after"), r7.get("editorBg"), r7.get("back")))
        check("深色切换写到了大文档视图宿主", r7.get("darkTheme") == "dark", str(r7.get("darkTheme")))
        check("背景色确实变了", r7.get("before") != r7.get("after"),
              "%s → %s" % (r7.get("before"), r7.get("after")))
        check("编辑器面板吃到深色", r7.get("editorBg") == r7.get("after"),
              "editor=%s host=%s" % (r7.get("editorBg"), r7.get("after")))
        check("切回浅色复位", r7.get("back") == r7.get("before"),
              "%s vs %s" % (r7.get("back"), r7.get("before")))
        check("主题切换无 JS 报错", not r7.get("errs"), str(r7.get("errs"))[:200])

        print("\n=== 8) 「显示行号」设置在大文档视图里同样生效 ===")
        open_editor()
        ev(client, big_case("menu"))
        r8 = json.loads(ev(client, r"""
            (async function(){
              var big=document.getElementById('bigView');
              function setLs(v){ return new Promise(function(res){
                chrome.storage.sync.set({lineNumbers:v}, res); }); }
              function gutterCount(){
                return big.querySelectorAll('.cm-gutters .cm-lineNumbers').length;
              }
              function digitText(){
                var g=big.querySelector('.cm-lineNumbers');
                return g ? (g.textContent||'').trim().slice(0,12) : '';
              }
              await setLs(false);
              await new Promise(function(r){setTimeout(r,600);});
              var offAfter = gutterCount(), offText = digitText();
              await setLs(true);
              await new Promise(function(r){setTimeout(r,600);});
              var onAfter = gutterCount(), onText = digitText();
              // 折叠槽不该被行号设置连坐
              var foldGutter = big.querySelectorAll('.cm-gutters .cm-foldGutter').length;
              var lines = big.querySelectorAll('.cm-line').length;
              await setLs(false);
              await new Promise(function(r){setTimeout(r,500);});
              return JSON.stringify({offAfter:offAfter, onAfter:onAfter,
                                     offText:offText, onText:onText,
                                     foldGutter:foldGutter, lines:lines,
                                     back:gutterCount(), errs:window.__errs||[]});
            })()
        """) or "{}")
        print("     关闭：行号槽=%s；开启：行号槽=%s（首行号 %r）→ 复位 %s；折叠槽=%s"
              % (r8.get("offAfter"), r8.get("onAfter"), r8.get("onText"),
                 r8.get("back"), r8.get("foldGutter")))
        check("默认关闭时无行号槽", (r8.get("offAfter") or 0) == 0, "gutter=%s" % r8.get("offAfter"))
        check("开启后出现行号槽且有行号", (r8.get("onAfter") or 0) > 0 and bool(r8.get("onText")),
              "gutter=%s text=%r" % (r8.get("onAfter"), r8.get("onText")))
        check("折叠槽不受行号设置影响", (r8.get("foldGutter") or 0) == 1,
              "foldGutter=%s" % r8.get("foldGutter"))
        check("改设置后仍正常渲染", (r8.get("lines") or 0) > 0, "lines=%s" % r8.get("lines"))
        check("设置切换无 JS 报错", not r8.get("errs"), str(r8.get("errs"))[:200])

        print("\n=== 9) 大文档：空间全给 JSON（单栏 + 收窄顶栏与底部状态带）===")

        # 9a) 先在新开的页面里格式化一份小 JSON：不该触发任何「最大化」布局
        open_editor()
        s3 = json.loads(ev(client, r"""
            (async function(){
              function box(sel){
                var e=document.querySelector(sel);
                if(!e) return null;
                var r=e.getBoundingClientRect();
                return {h:Math.round(r.height), w:Math.round(r.width)};
              }
              var el=document.getElementById('input');
              el.value='{"a":1,"b":[1,2,3]}';
              el.dispatchEvent(new InputEvent('input',{inputType:'insertFromPaste',bubbles:true}));
              await new Promise(function(r){setTimeout(r,900);});
              var ws=document.querySelector('.workspace');
              var jfs=document.querySelector('#viewer .jf-status');
              var fi=box('#panelInput .panel-foot');
              var fo=box('#panelOutput .panel-foot');
              return JSON.stringify({
                solo: ws.classList.contains('is-solo'),
                bigdoc: document.body.classList.contains('is-bigdoc'),
                inputH: box('#panelInput') ? box('#panelInput').h : -1,
                topbarH: box('.topbar').h,
                footInH: fi ? fi.h : -1,
                footOutH: fo ? fo.h : -1,
                jfStatusHidden: jfs ? getComputedStyle(jfs).display === 'none' : null,
                viewInfo: (document.getElementById('viewInfo')||{}).textContent,
                errs: window.__errs||[]
              });
            })()
        """) or "{}")
        print("     小文档：solo=%s bigdoc=%s 输入栏高=%s 顶栏=%s 底部带 左=%s/右=%s"
              % (s3.get("solo"), s3.get("bigdoc"), s3.get("inputH"), s3.get("topbarH"),
                 s3.get("footInH"), s3.get("footOutH")))
        print("             jf-status 隐藏=%s  主状态带镜像=%r"
              % (s3.get("jfStatusHidden"), s3.get("viewInfo")))
        check("小文档不触发最大化布局", s3.get("solo") is False and s3.get("bigdoc") is False,
              "solo=%s bigdoc=%s" % (s3.get("solo"), s3.get("bigdoc")))
        check("小文档下输入栏在位", (s3.get("inputH") or 0) > 0, "h=%s" % s3.get("inputH"))
        check("小文档下顶栏保持原高度", (s3.get("topbarH") or 0) >= 50, "h=%s" % s3.get("topbarH"))
        # 右栏底部曾同时叠着树视图的 .jf-status 与面板的 .panel-foot，
        # 比左栏多一行（实测 77px vs 34px）。这两条断言看着它不再回来。
        check("左右两栏底部状态带等高（不再叠两条）",
              (s3.get("footInH") or -1) == (s3.get("footOutH") or -2) and (s3.get("footInH") or 0) > 0,
              "左 %s / 右 %s" % (s3.get("footInH"), s3.get("footOutH")))
        check("树视图自带状态带已隐藏", s3.get("jfStatusHidden") is True,
              "display none=%s" % s3.get("jfStatusHidden"))
        check("节点统计已镜像进主状态带（信息没丢）",
              bool((s3.get("viewInfo") or "").strip()), "viewInfo=%r" % s3.get("viewInfo"))

        # 9b) 再粘贴大文档（同一页面内，不重新加载）
        r9 = json.loads(ev(client, r"""
            (async function(){
              function box(sel){
                var e=document.querySelector(sel);
                if(!e) return null;
                var r=e.getBoundingClientRect();
                return {h:Math.round(r.height), w:Math.round(r.width)};
              }
              var big=document.getElementById('bigView');
              var text=await (await fetch('http://127.0.0.1:__HTTP_PORT__/api/menu')).text();
              var dt=new DataTransfer(); dt.setData('text/plain', text);
              document.dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:dt,bubbles:true,cancelable:true}));
              for(var k=0;k<400;k++){
                await new Promise(function(r){setTimeout(r,50);});
                if(big.querySelector('.cm-line')) break;
              }
              await new Promise(function(r){setTimeout(r,600);});
              var ws=document.querySelector('.workspace');
              var msg=document.getElementById('msg');
              var lh=parseFloat(getComputedStyle(msg).lineHeight)||18;
              var btn=document.getElementById('btnSolo');
              var s1={
                solo: ws.classList.contains('is-solo'),
                bigdoc: document.body.classList.contains('is-bigdoc'),
                inputW: box('#panelInput') ? box('#panelInput').w : -1,
                bigH: box('#bigView').h,
                bigW: box('#bigView').w,
                topbarH: box('.topbar').h,
                footH: box('#panelOutput .panel-foot').h,
                msgH: Math.round(msg.getBoundingClientRect().height),
                lh: lh,
                pressed: btn.getAttribute('aria-pressed'),
                label: document.getElementById('soloLabel').textContent,
                viewInfo: (document.getElementById('viewInfo')||{}).textContent
              };
              btn.click();
              await new Promise(function(r){setTimeout(r,350);});
              var s2={
                solo: ws.classList.contains('is-solo'),
                inputW: box('#panelInput') ? box('#panelInput').w : -1,
                bigW: box('#bigView').w,
                pressed: btn.getAttribute('aria-pressed'),
                label: document.getElementById('soloLabel').textContent
              };
              return JSON.stringify({s1:s1, s2:s2, errs:window.__errs||[]});
            })()
        """.replace("__HTTP_PORT__", str(args.http_port))) or "{}")

        s1 = r9.get("s1") or {}
        s2 = r9.get("s2") or {}
        print("     大文档：solo=%s bigdoc=%s 输入栏宽=%s JSON %sx%s 顶栏=%s 底部=%s 文案高=%s(行高 %s)"
              % (s1.get("solo"), s1.get("bigdoc"), s1.get("inputW"), s1.get("bigW"),
                 s1.get("bigH"), s1.get("topbarH"), s1.get("footH"),
                 s1.get("msgH"), s1.get("lh")))
        print("     点「显示输入」：solo=%s 输入栏宽=%s JSON 宽=%s 按钮=%s/%r"
              % (s2.get("solo"), s2.get("inputW"), s2.get("bigW"),
                 s2.get("pressed"), s2.get("label")))

        check("大文档自动收起输入栏", s1.get("solo") is True)
        check("大文档标记已挂上", s1.get("bigdoc") is True)
        check("输入栏不占宽度", s1.get("inputW") == 0, "w=%s" % s1.get("inputW"))
        check("JSON 占满整宽（>1200px）", (s1.get("bigW") or 0) > 1200, "w=%s" % s1.get("bigW"))
        check("JSON 高度 > 790px", (s1.get("bigH") or 0) > 790, "h=%s" % s1.get("bigH"))
        check("顶栏收窄到 <50px", (s1.get("topbarH") or 999) < 50, "h=%s" % s1.get("topbarH"))
        check("底部状态带 <34px", (s1.get("footH") or 999) < 34, "h=%s" % s1.get("footH"))
        check("底部文案单行不换行（不再像两排）",
              (s1.get("msgH") or 999) <= (s1.get("lh") or 18) * 1.6,
              "文案高 %s / 行高 %s" % (s1.get("msgH"), s1.get("lh")))
        check("按钮语义为「显示输入」",
              s1.get("pressed") == "true" and s1.get("label") == "显示输入",
              "%s / %s" % (s1.get("pressed"), s1.get("label")))
        check("点击后输入栏回来", s2.get("solo") is False and (s2.get("inputW") or 0) > 0,
              "solo=%s w=%s" % (s2.get("solo"), s2.get("inputW")))
        check("输入栏回来后 JSON 让出宽度", (s2.get("bigW") or 9999) < (s1.get("bigW") or 0),
              "%s -> %s" % (s1.get("bigW"), s2.get("bigW")))
        check("按钮状态与文案同步",
              s2.get("pressed") == "false" and s2.get("label") == "输入栏",
              "%s / %s" % (s2.get("pressed"), s2.get("label")))
        # 大文档走 CodeMirror 宿主，没有树视图，镜像文字必须清掉，
        # 否则左栏的节点统计会「粘」在右栏底部。
        check("大文档下树视图统计已清空",
              not (s1.get("viewInfo") or "").strip(), "viewInfo=%r" % s1.get("viewInfo"))
        check("布局切换无 JS 报错", not r9.get("errs") and not s3.get("errs"),
              str((r9.get("errs") or []) + (s3.get("errs") or []))[:200])

        print("\n" + "=" * 52)
        if fails:
            print("[失败] %d 项：" % len(fails))
            for f in fails:
                print("  - " + f)
            return 6
        print("[通过] 扩展 v1.1.6 本地验收全部符合预期")
        return 0
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
