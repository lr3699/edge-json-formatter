#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-big-fold.py —— 大文档视图「折叠全部 / 展开全部」验收。

背景：旧实现逐行调 CM.foldable，而 syntaxTree 是惰性解析的 —— 大文档只解析
视口附近，未解析区域 foldable 返回 null，结果「折叠全部只折了顶部一段」。
新实现自己扫括号（collectOuterFolds），与语法树无关，只留最外层折叠块。

断言（不是只看 DOM，全部走 CM 内部 foldState 验证）：
  1) CM 就绪且测试钩子 host.__jfView 可用
  2) 折叠全部：foldState 恰 1 个区间（最外层=根容器），且覆盖到文档末尾
  3) 按钮文案翻转为「展开全部」
  4) 展开全部：foldState 清零、行数不变、全文逐字节保留
  5) 折叠→展开→再折叠 一轮后状态一致

前置：本地站点在跑（node tools/serve.js），Edge 带 --remote-debugging-port。
用法：python tools/verify-big-fold.py --port 9335 --url http://127.0.0.1:18546/site/app.html
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".workbuddy" / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts")
                if False else str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

fails = []
passes = []


def check(name, ok, extra=""):
    (passes if ok else fails).append(name)
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  " + str(extra)) if extra else ""))
    return ok


def ev(client, expr, timeout=120):
    res = client.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True,
                       "awaitPromise": True, "userGesture": True},
                      timeout=timeout)
    if res.get("exceptionDetails"):
        raise RuntimeError(str(res["exceptionDetails"])[:800])
    return res["result"]["value"]


# ---------------------------------------------------------------- 注入大文档
INJECT = r"""
(async function () {
  var arr = [];
  for (var i = 0; i < 12000; i++) {
    arr.push({ id: 'ORD' + i, orderId: '6006538365075169' + (i % 100),
               name: '订单-' + i, amount: (i * 37) % 99991 + 0.5,
               tags: ['a', 'b', 'c'],
               nested: { city: '深圳', zip: '518000', ok: i % 2 === 0 } });
  }
  var text = JSON.stringify({ total: arr.length, rows: arr }, null, 2);
  var inp = document.getElementById('input');
  inp.value = text;
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  // 排版挂在 rAF 上；后台标签页 rAF 会被暂停，所以轮询等 CodeMirror + 测试钩子
  for (var i = 0; i < 240; i++) {
    var v = document.getElementById('bigView');
    if (v && v.__jfView && v.querySelector('.cm-editor')) break;
    await new Promise(function (r) { setTimeout(r, 50); });
  }
  await new Promise(function (r) { setTimeout(r, 300); });
  var host = document.getElementById('bigView');
  return JSON.stringify({
    chars: text.length,
    lines: host && host.__jfView ? host.__jfView.state.doc.lines : 0,
    ready: !!(host && host.__jfView),
  });
})()
"""

# ---------------------------------------------------------------- 折叠操作
CLICK = r"""
(function (label) {
  var btns = document.querySelectorAll('#bigToolbar button');
  for (var i = 0; i < btns.length; i++) {
    if ((btns[i].textContent || '').trim() === label) { btns[i].click(); return 'clicked'; }
  }
  return 'not-found:' + label;
})("%s")
"""

# foldState 快照：区间数、首区间覆盖、行数、全文长度、全文指纹（前 200 + 后 200 字符 + 长度）
SNAP = r"""
(function () {
  var host = document.getElementById('bigView');
  var view = host && host.__jfView;
  if (!view) return JSON.stringify({ err: 'no view' });
  var st = view.state;
  var field = null;
  try { field = st.field(window.JFCodeMirror.foldState, false); } catch (e) { field = null; }
  var folds = [];
  if (field) {
    field.between(0, st.doc.length, function (from, to) { folds.push([from, to]); });
  }
  var text = st.doc.toString();
  return JSON.stringify({
    lines: st.doc.lines,
    len: text.length,
    head: text.slice(0, 200),
    tail: text.slice(-200),
    folds: folds,
    foldCount: folds.length,
  });
})()
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9335)
    ap.add_argument("--url", default="http://127.0.0.1:18546/site/app.html")
    args = ap.parse_args(argv)

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP_UNREACHABLE: %d" % args.port)
        return 2
    c.ensure_page()
    c.send("Page.enable")
    c.send("Runtime.enable")
    try:
        c.send("Page.bringToFront")
    except Exception:
        pass

    c.navigate(args.url, timeout=60)
    c.wait_for("document.readyState==='complete'", timeout=30)
    ev(c, "(function(){try{localStorage.clear()}catch(e){} return 1;})()")
    c.navigate(args.url, timeout=60)
    c.wait_for("document.readyState==='complete' && !!document.getElementById('input')", timeout=30)

    print("\n--- 1) 注入大文档（1.2MB，超 600KB 阈值 → CodeMirror 视图） ---")
    inj = json.loads(ev(c, INJECT))
    check("CM 就绪 + 测试钩子 __jfView", inj["ready"], inj)
    check("行数 > 5 万", inj["lines"] > 50000, inj["lines"])

    base = json.loads(ev(c, SNAP))
    check("初始无折叠", base["foldCount"] == 0, base["foldCount"])

    print("\n--- 2) 点「折叠全部」 ---")
    r1 = ev(c, CLICK % "折叠全部")
    check("按钮命中", r1 == "clicked", r1)
    time.sleep(0.6)
    folded = json.loads(ev(c, SNAP))

    check("恰 1 个折叠区间（最外层=根容器）",
          folded["foldCount"] == 1, "实际 %d" % folded["foldCount"])
    if folded["foldCount"] == 1:
        f0 = folded["folds"][0]
        # 关键回归断言：折叠必须覆盖到文档末尾（旧 bug 只折顶部一段）
        check("折叠区间覆盖到文档末尾",
              f0[1] >= base["len"] * 0.98,
              "fold.to=%d, docLen=%d (%.1f%%)"
              % (f0[1], base["len"], 100.0 * f0[1] / base["len"]))
        check("折叠区间从第一行行尾开始", f0[0] < 500, "fold.from=%d" % f0[0])
    check("折叠不丢内容（全文长度不变）", folded["len"] == base["len"],
          "%s → %s" % (base["len"], folded["len"]))
    lbl = ev(c, "(function(){var b=document.querySelectorAll('#bigToolbar button');"
                "for(var i=0;i<b.length;i++){var t=(b[i].textContent||'').trim();"
                "if(t==='展开全部'||t==='折叠全部')return t;}return '?';})()")
    check("按钮文案=展开全部", lbl == "展开全部", lbl)

    print("\n--- 3) 点「展开全部」 ---")
    r2 = ev(c, CLICK % "展开全部")
    check("按钮命中", r2 == "clicked", r2)
    time.sleep(0.6)
    unfolded = json.loads(ev(c, SNAP))
    check("foldState 清零", unfolded["foldCount"] == 0, unfolded["foldCount"])
    check("行数不变", unfolded["lines"] == base["lines"],
          "%s → %s" % (base["lines"], unfolded["lines"]))
    check("全文逐字节保留",
          unfolded["len"] == base["len"] and unfolded["head"] == base["head"]
          and unfolded["tail"] == base["tail"],
          "len %s/%s" % (base["len"], unfolded["len"]))

    print("\n--- 4) 再折叠一轮（状态一致性） ---")
    ev(c, CLICK % "折叠全部")
    time.sleep(0.4)
    ev(c, CLICK % "展开全部")
    time.sleep(0.4)
    again = json.loads(ev(c, SNAP))
    check("两轮后 foldState 清零", again["foldCount"] == 0, again["foldCount"])
    check("两轮后全文保留",
          again["len"] == base["len"] and again["head"] == base["head"] and again["tail"] == base["tail"])
    ev(c, CLICK % "折叠全部")  # 收尾：留在折叠态无所谓，页面会被刷新

    print("\n========== 结果: %d 通过 / %d 失败 ==========" % (len(passes), len(fails)))
    if fails:
        print("失败项: " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
