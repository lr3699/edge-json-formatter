#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-ext-115.py —— 对 **已加载到浏览器里的扩展**（dist/unpacked）做一次线上前验收。

跟 verify-local.py 的区别：这个脚本自带一个本地 JSON 服务，不需要额外起服务；
并且把「折叠 → 再展开，子元素是否重复追加」这条回归在真实扩展环境里钉死
（这个 bug 只会在内容脚本接管页面后、由查看器的状态机触发，网页版跑通不等于扩展跑通）。

覆盖：
  1. 扩展已加载 + service worker 就位
  2. JSON 接口被内容脚本自动接管，树渲染成功、无 JS 报错
  3. 折叠 → 展开 ×3：行数不增长、无重复元素、行号连续无断档   ← 回归主项
  4. 后台还在分帧补行时连点折叠/展开：不重复、不卡死            ← 同类状态机隐患
  5. 编辑页可用（粘贴 → 格式化成功）
  6. 大 JSON（23MB 夹具）走编辑页：有行数上限、不超时

用法：
    python tools/verify-ext-115.py [--port 9333] [--http-port 18555]
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

from cdp import CDPClient, CDPError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BIG_FIXTURE = ROOT / "tools" / "fixtures" / "big-20mb.json"
MENU_FIXTURE = ROOT / "tools" / "fixtures" / "big-menu.json"

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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/order"):
            self._json(SAMPLE)
        elif self.path.startswith("/api/big") or self.path.startswith("/api/menu"):
            fixture = MENU_FIXTURE if self.path.startswith("/api/menu") else BIG_FIXTURE
            body = fixture.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def start_server(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def unpacked_extension_id(path):
    """本地加载（未打包）扩展的 ID = sha256(绝对路径的 UTF-16LE 编码) 前 16 字节，逐 nibble 映射到 a..p。

    这条很有用：MV3 的 service worker 空闲后会被回收，/json/list 里就没这条 target 了，
    查不到 ID 就导航不了扩展页面。用路径反推是确定性的，不依赖 SW 是否活着。
    （Windows 上必须用 UTF-16LE；用 UTF-8 得到的是另一个 ID。）
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


def ev(client, expr, timeout=180.0):
    """evaluate 的 awaitPromise 版：本脚本大量使用 async IIFE，
    而 CDPClient.evaluate 固定 awaitPromise=False，拿到的是 Promise 对象而不是值。"""
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
                    help="未打包扩展目录（用于在 SW 已回收时反推扩展 ID）")
    ap.add_argument("--shot", help="截图保存路径")
    args = ap.parse_args()

    base = "http://127.0.0.1:%d" % args.http_port
    srv = start_server(args.http_port)
    fails = []

    def check(name, cond, extra=""):
        print("  [%s] %-32s %s" % ("PASS" if cond else "FAIL", name, extra))
        if not cond:
            fails.append(name)

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

        # ---------- 1) 内容脚本自动接管 ----------
        print("\n=== 1) JSON 接口自动接管 ===")
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
            "ct: document.contentType,"
            "errors: window.__errs||[]});})()"
        ) or "{}")
        check("内容脚本接管页面", r1.get("takenOver"), "rows=%s" % r1.get("rows"))
        check("查看器工具栏存在", r1.get("toolbar"))
        check("接管过程无 JS 报错", not r1.get("errors"), str(r1.get("errors"))[:160])

        # ---------- 2) 折叠 → 展开 ×3：不得重复追加 ----------
        print("\n=== 2) 折叠再展开（回归主项）===")
        probe = (
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
            toggleFirst();                        // 折叠
            await new Promise(function(r){setTimeout(r,260);});
            toggleFirst();                        // 再展开
            await new Promise(function(r){setTimeout(r,420);});
            after.push(snap());
          }
          var final=snap();
          return JSON.stringify({
            before:before, after:after, final:final,
            grew: final.rows>before.rows,
            rowsStable: after.every(function(s){return s.rows===after[0].rows;}),
            keysStable: after.every(function(s){return s.keys===after[0].keys;}),
            errors: window.__errs||[]
          });
        })()
        """
        )
        r2 = json.loads(ev(client, probe) or "{}")
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
        # 行号是设置项、默认关闭；关着时 .jf-no 全为空属正常，只在开启时断言没有空缺
        fin = r2.get("final") or {}
        nums_on = (fin.get("emptyNos") or 0) < (fin.get("rows") or 0)
        if nums_on:
            check("行号无空缺", fin.get("emptyNos") == 0, "empty=%s" % fin.get("emptyNos"))
        else:
            print("  [INFO] 行号设置默认关闭（.jf-no 全空），跳过「行号无空缺」断言")
        check("折叠展开无 JS 报错", not r2.get("errors"), str(r2.get("errors"))[:160])
        if args.shot:
            client.screenshot(args.shot)
            print("     截图:", args.shot)

        # ---------- 3) 后台补帧期间连点 ----------
        print("\n=== 3) 后台分帧补行时连点折叠/展开 ===")
        r3 = json.loads(ev(client, (
            "(async function(){"
            + JF_ROOT +
            """
              var v=__jfRoot();
              var t=v.querySelector('.jf-toggle');
              var before=v.querySelectorAll('.jf-row').length;
              for(var c=0;c<4;c++){
                if(t) t.click();
                await new Promise(function(r){setTimeout(r,60);});
                if(t) t.click();
                await new Promise(function(r){setTimeout(r,60);});
              }
              await new Promise(function(r){setTimeout(r,1400);});
              var rows=v.querySelectorAll('.jf-row').length;
              var nos=[].slice.call(v.querySelectorAll('.jf-no'));
              var breaks=0, empty=0, prev=null;
              for(var j=0;j<nos.length;j++){
                var s=(nos[j].textContent||'').trim();
                if(!s){empty++;continue;}
                var n=parseInt(s,10); if(isNaN(n)) continue;
                if(prev!==null && n!==prev+1) breaks++;
                prev=n;
              }
              return JSON.stringify({before:before, after:rows, breaks:breaks,
                                     emptyNos:empty, errors:window.__errs||[]});
            })()
            """
        )) or "{}")
        check("连点后行数未异常增长",
              r3.get("after") is not None and r3.get("after") <= max(r3.get("before", 0), 1) * 8,
              "before=%s after=%s" % (r3.get("before"), r3.get("after")))
        check("连点后行号连续", r3.get("breaks") == 0, "breaks=%s" % r3.get("breaks"))
        if (r3.get("emptyNos") or 0) < (r3.get("after") or 0):
            check("连点后行号无空缺", r3.get("emptyNos") == 0, "empty=%s" % r3.get("emptyNos"))
        else:
            print("  [INFO] 行号设置默认关闭，跳过「连点后行号无空缺」断言")
        check("连点无 JS 报错", not r3.get("errors"), str(r3.get("errors"))[:160])

        # ---------- 4) 编辑页 ----------
        print("\n=== 4) 粘贴 JSON 编辑页 ===")
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30)
        client.wait_for("document.readyState==='complete' && !!document.getElementById('input')",
                        timeout=15)
        time.sleep(0.8)
        r4 = json.loads(ev(client,
            r"""
            (async function(){
              var el=document.getElementById('input');
              var host=document.getElementById('viewer');
              el.value='{"a":1,"b":[true,null,"x"],"c":{"d":600653836507516928}}';
              el.dispatchEvent(new InputEvent('input',{inputType:'insertFromPaste',bubbles:true}));
              await new Promise(function(r){setTimeout(r,900);});
              return JSON.stringify({
                rows: host.querySelectorAll('.jf-row').length,
                pill: document.getElementById('pillText').textContent,
                hasKey: !!host.querySelector('.jf-key'),
                errors: window.__errs||[]
              });
            })()
            """
        ) or "{}")
        check("编辑页渲染出树", (r4.get("rows") or 0) > 3, "rows=%s" % r4.get("rows"))
        check("编辑页格式化成功", "成功" in (r4.get("pill") or ""), str(r4.get("pill")))
        check("大整数未丢精度",
              bool(client.evaluate(
                  "(document.getElementById('viewer').innerText||'').indexOf('600653836507516928')>=0"
              ).get("value")))
        check("编辑页无 JS 报错", not r4.get("errors"), str(r4.get("errors"))[:160])

        # ---------- 5) 大 JSON ----------
        # 分两档：自动上限内（应直接格式化成功）、超上限（按设计给「内容过大」提示，
        # 不自动渲染以免刚载入就卡住；强制格式化走 Ctrl+Enter）。
        BIG_JS = r"""
            (async function(){
              window.__errs=[];
              var el=document.getElementById('input');
              var host=document.getElementById('viewer');
              var res=await fetch('http://127.0.0.1:__HTTP_PORT__/api/__WHICH__');
              var text=await res.text();
              var t0=performance.now();
              if(__PASTE__){
                // 走真实粘贴路径：编辑器会拦截粘贴、把大文本放内存源、不写回 textarea。
                // 这是「大 JSON 不卡」的关键（textarea 渲染 10MB 文本本身就要十几秒）。
                var dt=new DataTransfer();
                dt.setData('text/plain', text);
                document.dispatchEvent(new ClipboardEvent('paste',
                  {clipboardData:dt,bubbles:true,cancelable:true}));
              } else {
                el.value=text;
                el.dispatchEvent(new InputEvent('input',{inputType:'insertFromPaste',bubbles:true}));
                if(__FORCE__) el.dispatchEvent(new KeyboardEvent('keydown',
                  {key:'Enter',code:'Enter',keyCode:13,which:13,ctrlKey:true,bubbles:true,cancelable:true}));
              }
              var rows=0, t1=null;
              for(var k=0;k<300;k++){
                await new Promise(function(r){setTimeout(r,100);});
                rows=host.querySelectorAll('.jf-row').length;
                if(rows>0){t1=performance.now();break;}
              }
              await new Promise(function(r){setTimeout(r,900);});
              rows=host.querySelectorAll('.jf-row').length;
              var more=host.querySelector('.jf-summary');
              return JSON.stringify({
                chars:text.length,
                msToRows: t1===null?null:Math.round(t1-t0),
                rows:rows, more:more?more.textContent:null,
                pill:document.getElementById('pillText').textContent,
                msg:(document.getElementById('msg')||{}).textContent,
                textareaLen: el.value.length,
                errors:window.__errs||[]
              });
            })()
        """

        def big_case(which, force=False, paste=False):
            return (BIG_JS.replace("__HTTP_PORT__", str(args.http_port))
                          .replace("__WHICH__", which)
                          .replace("__FORCE__", "true" if force else "false")
                          .replace("__PASTE__", "true" if paste else "false"))

        def open_editor():
            client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30)
            client.wait_for("document.readyState==='complete' && !!document.getElementById('input')",
                            timeout=15)
            time.sleep(0.9)

        print("\n=== 5a) 上限内的 11MB JSON —— 真实粘贴路径（应秒开）===")
        open_editor()
        r5 = json.loads(ev(client, big_case("menu", paste=True), timeout=300.0) or "{}")
        print("     字符数=%s 耗时=%sms 行数=%s 摘要=%s textarea残留=%s"
              % (r5.get("chars"), r5.get("msToRows"), r5.get("rows"),
                 r5.get("more"), r5.get("textareaLen")))
        check("11MB 粘贴后格式化成功", "成功" in (r5.get("pill") or ""), str(r5.get("pill")))
        check("11MB 粘贴未超时", r5.get("msToRows") is not None, "%sms" % r5.get("msToRows"))
        check("11MB 粘贴避开了 textarea 渲染",
              (r5.get("textareaLen") or 0) < (r5.get("chars") or 0),
              "textarea=%s / 原文=%s" % (r5.get("textareaLen"), r5.get("chars")))
        check("11MB 行数受闸门控制", (r5.get("rows") or 0) <= 8000, "rows=%s" % r5.get("rows"))
        check("11MB 有「加载更多」提示", bool(r5.get("more")), str(r5.get("more")))

        print("\n=== 5b) 超上限的 23MB JSON（应给「内容过大」提示、不卡死）===")
        open_editor()
        r6 = json.loads(ev(client, big_case("big"), timeout=300.0) or "{}")
        print("     字符数=%s 行数=%s 胶囊=%s 文案=%s"
              % (r6.get("chars"), r6.get("rows"), r6.get("pill"), (r6.get("msg") or "")[:60]))
        check("23MB 给出「内容过大」提示", "内容过大" in (r6.get("pill") or ""), str(r6.get("pill")))
        check("23MB 未自动渲染（按设计）", (r6.get("rows") or 0) == 0, "rows=%s" % r6.get("rows"))
        check("23MB 无 JS 报错", not r6.get("errors"), str(r6.get("errors"))[:160])

        print("\n=== 5c) 23MB 强制格式化（Ctrl+Enter，应能出树）===")
        open_editor()
        r7 = json.loads(ev(client, big_case("big", force=True), timeout=300.0) or "{}")
        print("     字符数=%s 耗时=%sms 行数=%s"
              % (r7.get("chars"), r7.get("msToRows"), r7.get("rows")))
        check("23MB 强制格式化成功", "成功" in (r7.get("pill") or ""), str(r7.get("pill")))
        check("23MB 强制格式化行数受控", (r7.get("rows") or 0) <= 8000, "rows=%s" % r7.get("rows"))
        check("23MB 强制格式化无 JS 报错", not r7.get("errors"), str(r7.get("errors"))[:160])

        print("\n" + "=" * 46)
        if fails:
            print("[失败] %d 项：" % len(fails))
            for f in fails:
                print("  - " + f)
            return 6
        print("[通过] 扩展 v1.1.5 本地验收全部符合预期")
        return 0
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
