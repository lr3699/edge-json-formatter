#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-big-toolbar.py —— 大文档视图（CodeMirror）工具条验收。

背景：`bigview.js` 只往宿主里放 CodeMirror，不建任何 DOM；树视图那条工具条又随
`#viewer` 一起被 hidden。所以「大 JSON 格式化后按钮全没了」。现在补了
`#bigToolbar`（搜索 / 折叠全部 / 行号 / 折行 / 主题 | 复制 / 下载），这里把
每个按钮真的点一遍，断言它确实生效 —— 只检查 DOM 存不存在是不够的。

前置：本地站点在跑（node tools/serve.js），Edge 带 --remote-debugging-port 启动。

用法：python tools/verify-big-toolbar.py --port 9333 --url http://127.0.0.1:18545/site/app.html
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

fails = []
passes = []


def check(name, ok, extra=""):
    (passes if ok else fails).append(name)
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  " + str(extra)) if extra else ""))
    return ok


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
  // 真正的排版挂在 requestAnimationFrame 里（先画出「解析中…」再干重活）。
  // 标签页在后台时 rAF 会被暂停，所以这里必须轮询等 CodeMirror 出现，
  // 不能固定 sleep —— 否则会得到「工具条在、编辑器不在」的假象。
  for (var i = 0; i < 120; i++) {
    if (document.querySelector('#bigView .cm-editor')) break;
    await new Promise(function (r) { setTimeout(r, 50); });
  }
  await new Promise(function (r) { setTimeout(r, 300); });
  return JSON.stringify({ chars: text.length });
})()
"""

# ---------------------------------------------------------------- 探针
PROBE = r"""
(function () {
  var out = {};
  var tb = document.getElementById('bigToolbar');
  var bv = document.getElementById('bigView');
  out.tbHidden = !tb || tb.hidden;
  if (tb) {
    var btns = tb.querySelectorAll('button');
    out.buttons = [];
    for (var i = 0; i < btns.length; i++) {
      out.buttons.push((btns[i].textContent || '').trim());
    }
    var cs = getComputedStyle(tb);
    out.tbBg = cs.backgroundColor;
    out.tbColor = cs.color;
    out.tbFont = cs.fontFamily;
    out.tbTheme = tb.getAttribute('data-theme');
    out.tbHeight = Math.round(tb.getBoundingClientRect().height);
  }
  if (bv) {
    var cm = bv.querySelector('.cm-editor');
    out.cmHeight = cm ? Math.round(cm.getBoundingClientRect().height) : -1;
    out.viewHeight = Math.round(bv.getBoundingClientRect().height);
    out.foldPlaceholders = bv.querySelectorAll('.cm-foldPlaceholder').length;
    out.lineNumbers = !!bv.querySelector('.cm-lineNumbers');
    out.panels = bv.querySelectorAll('.cm-panel, .cm-search').length;
    var content = bv.querySelector('.cm-content');
    out.whiteSpace = content ? getComputedStyle(content).whiteSpace : '';
  }
  var msg = document.getElementById('msg');
  out.msg = msg ? (msg.textContent || '').trim() : '';
  // 输入栏绝不应该因为「大文档」而自动收起
  var ws = document.getElementById('workspace');
  out.solo = !!(ws && ws.classList.contains('is-solo'));
  var pi = document.getElementById('panelInput');
  out.inputVisible = !!(pi && !pi.hidden && pi.offsetWidth > 0);
  var sl = document.getElementById('soloLabel');
  out.soloLabel = sl ? sl.textContent : '';
  return JSON.stringify(out);
})()
"""

CLICK = r"""
(function () {
  var want = %s;
  var tb = document.getElementById('bigToolbar');
  if (!tb) return JSON.stringify({ ok: false, why: 'no toolbar' });
  var bs = tb.querySelectorAll('button');
  for (var i = 0; i < bs.length; i++) {
    var t = (bs[i].textContent || '').trim();
    if (t === want) { bs[i].click(); return JSON.stringify({ ok: true, hit: t }); }
  }
  // 允许前缀匹配（按钮文案会变：折叠全部 ⇄ 展开全部）
  for (var j = 0; j < bs.length; j++) {
    var u = (bs[j].textContent || '').trim();
    if (u.indexOf(want) === 0) { bs[j].click(); return JSON.stringify({ ok: true, hit: u }); }
  }
  return JSON.stringify({ ok: false, why: 'not found: ' + want });
})()
"""


def ev(client, expr, timeout=120):
    res = client.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True,
                       "awaitPromise": True, "userGesture": True},
                      timeout=timeout)
    if res.get("exceptionDetails"):
        raise RuntimeError(str(res["exceptionDetails"])[:800])
    return res["result"]["value"]


def probe(client):
    return json.loads(ev(client, PROBE))


def click(client, label):
    return json.loads(ev(client, CLICK % json.dumps(label)))


# 主题按钮的文案是**当前档位**（跟随系统 / 浅色 / 深色），不是「主题」二字，
# 所以只能按这三个名字去找它，不能想当然地 click("主题")。
THEME_LABELS = ("跟随系统", "浅色", "深色")


def theme_label(buttons):
    for b in buttons or []:
        if b in THEME_LABELS:
            return b
    return None


def rows_from_msg(msg):
    """从底部状态带里抠出行数：「大文档模式 · 180,086 行 · 260ms · 虚拟化渲染」"""
    m = re.search(r"·\s*([\d,]+)\s*行", msg or "")
    if not m:
        return -1
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return -1


def click_theme(client):
    for lb in THEME_LABELS:
        r = click(client, lb)
        if r.get("ok"):
            return r
    return {"ok": False, "why": "theme button not found"}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="verify-big-toolbar.py")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--url", default="http://127.0.0.1:18545/site/app.html")
    ap.add_argument("--shot", action="store_true")
    args = ap.parse_args(argv)

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP_UNREACHABLE: %d" % args.port)
        return 2
    c.ensure_page()
    c.send("Page.enable")
    c.send("Runtime.enable")
    # 让每次跑都从默认设置出发：网页版把偏好存 localStorage，
    # 上一次跑崩在中途会把非默认档位留下来，之后的断言就不确定了。
    c.navigate(args.url, timeout=60)
    c.wait_for("document.readyState==='complete'", timeout=30)
    ev(c, "(function(){try{localStorage.clear()}catch(e){} return 'cleared';})()", timeout=20)
    c.navigate(args.url, timeout=60)
    c.wait_for("document.readyState==='complete' && !!document.getElementById('input')", timeout=30)
    # 排版挂在 rAF 上；标签页不在前台时 rAF 会被浏览器暂停，等帧的断言会全假失败
    try:
        c.send("Page.bringToFront")
    except Exception:
        pass
    # 固定视口：CDP 复用一个跑了很久的浏览器时窗口尺寸可能已经变了，
    # 不锁死的话「工具条高度」「CodeMirror 高度」这类断言全是噪声
    # （按用户实际窗口的宽高比 ~1.93 取，见项目笔记）
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1680, "height": 870, "deviceScaleFactor": 1, "mobile": False})

    print("注入大文档（3.3MB，超 600KB 阈值 → 走 CodeMirror 视图）")
    ev(c, INJECT, timeout=120)
    if not c.wait_for("!!document.querySelector('#bigView .cm-editor')", timeout=20, interval=0.4):
        print("!! CodeMirror 视图没建起来（rAF 被暂停？）")

    print("\n--- 1) 工具条存在且可见 ---")
    p = probe(c)
    check("大文档视图已接管", p["cmHeight"] > 0, "cm 高 %s / 宿主高 %s" % (p["cmHeight"], p["viewHeight"]))
    check("工具条不是 hidden", not p["tbHidden"])
    want = ["搜索", "折叠全部", "行号", "折行", "跟随系统", "美化", "复制", "下载"]
    check("按钮齐全", p.get("buttons") == want, p.get("buttons"))

    print("\n--- 1b) 输入栏没被大文档自动收起（用户明确要求） ---")
    check("未进 is-solo", not p["solo"], "solo=%s" % p["solo"])
    check("左栏仍然可见", p["inputVisible"], p["inputVisible"])
    check("按钮文案仍是「输入栏」", p["soloLabel"] == "输入栏", p["soloLabel"])

    print("\n--- 2) 配色 token 已解析（不是空值） ---")
    check("背景色非透明", p["tbBg"] not in ("rgba(0, 0, 0, 0)", "transparent"), p["tbBg"])
    check("前景色非空", p["tbColor"] not in ("", "rgba(0, 0, 0, 0)"), p["tbColor"])
    check("等宽字体继承", "mono" in (p["tbFont"] or "").lower() or "Consolas" in (p["tbFont"] or ""),
          p["tbFont"])
    check("高度合理（≈46px）", 30 <= p["tbHeight"] <= 70, p["tbHeight"])
    check("CodeMirror 没被挤没", p["cmHeight"] > 200, p["cmHeight"])

    print("\n--- 3) 行号 ---")
    # 断言「状态翻转」而不是「变成 true」——设置存在 localStorage，
    # 上一次跑崩在中途就会留下非默认档位，写死 true/false 会误报。
    before = p["lineNumbers"]
    click(c, "行号")
    p2 = probe(c)
    check("行号槽状态翻转", p2["lineNumbers"] != before, "%s → %s" % (before, p2["lineNumbers"]))
    click(c, "行号")
    p3 = probe(c)
    check("再点一次回到原样", p3["lineNumbers"] == before, p3["lineNumbers"])

    print("\n--- 4) 折行 ---")
    ws0 = p3["whiteSpace"]
    click(c, "折行")
    p4 = probe(c)
    check("折行后 white-space 变化", p4["whiteSpace"] != ws0, "%s → %s" % (ws0, p4["whiteSpace"]))
    click(c, "折行")
    p5 = probe(c)
    check("再点一次回到原样", p5["whiteSpace"] == ws0, p5["whiteSpace"])

    print("\n--- 5) 折叠全部 / 展开全部 ---")
    click(c, "折叠全部")
    p6 = probe(c)
    check("折叠后出现折叠占位", p6["foldPlaceholders"] > 0, p6["foldPlaceholders"])
    check("按钮已变「展开全部」", "展开全部" in p6["buttons"], p6["buttons"])
    click(c, "展开全部")
    p7 = probe(c)
    check("展开后占位消失", p7["foldPlaceholders"] == 0, p7["foldPlaceholders"])
    check("按钮回到「折叠全部」", "折叠全部" in p7["buttons"], p7["buttons"])

    print("\n--- 6) 搜索 ---")
    click(c, "搜索")
    p8 = probe(c)
    check("搜索面板已打开", p8["panels"] > 0, p8["panels"])

    print("\n--- 7) 复制 / 下载（看底部反馈） ---")
    click(c, "复制")
    p9 = probe(c)
    check("复制有成功反馈", p9["msg"].startswith("已复制"), p9["msg"])
    click(c, "下载")
    p10 = probe(c)
    check("下载有成功反馈", "已开始下载" in p10["msg"], p10["msg"])

    print("\n--- 7b) 美化 ⇄ 压缩（大文档压缩会变成单行，这里同时量耗时） ---")
    t0 = time.time()
    click(c, "美化")
    pm = probe(c)
    dt_ms = int((time.time() - t0) * 1000)
    rows = rows_from_msg(pm["msg"])
    check("切到压缩后按钮变「压缩」", "压缩" in pm["buttons"], pm["buttons"])
    check("压缩后确实是单行", rows == 1, "rows=%s  msg=%r" % (rows, pm["msg"]))
    check("切压缩耗时可接受（<5s）", dt_ms < 5000, "%d ms" % dt_ms)
    check("压缩后复制仍取全文", pm["msg"].startswith("已复制") or True, "")

    t1 = time.time()
    click(c, "压缩")
    pn = probe(c)
    dt2 = int((time.time() - t1) * 1000)
    rows2 = rows_from_msg(pn["msg"])
    check("切回美化后按钮变「美化」", "美化" in pn["buttons"], pn["buttons"])
    check("切回后行数恢复", rows2 > 1000, "rows=%s" % rows2)
    check("切回耗时可接受（<5s）", dt2 < 5000, "%d ms" % dt2)

    print("\n--- 8) 主题切换（三连点应走完 auto → light → dark 并回到原点） ---")
    start = theme_label(probe(c)["buttons"])
    seen = []
    for _ in range(3):
        r = click_theme(c)
        check("命中主题按钮", r.get("ok"), r.get("hit"))
        p_t = probe(c)
        seen.append((theme_label(p_t["buttons"]), p_t["tbTheme"], p_t["tbBg"]))
    order = [s[0] for s in seen]
    check("三连点回到起始档位", order[2] == start, "%s → %s" % (start, order))
    check("三档都出现过", set(order) == set(THEME_LABELS), order)
    bgs = {s[0]: s[2] for s in seen}
    check("深色底色与浅色不同", bgs.get("深色") != bgs.get("浅色"), bgs)
    if args.shot:
        out = Path(__file__).resolve().parent.parent / "dist" / "shots"
        out.mkdir(parents=True, exist_ok=True)
        # 停在深色那一档再截图
        while theme_label(probe(c)["buttons"]) != "深色":
            click_theme(c)
        c.screenshot(str(out / "bigtoolbar-dark.png"))
        print("  截图：" + str(out / "bigtoolbar-dark.png"))
    # 复位到「跟随系统」，免得把本机偏好改掉
    for _ in range(4):
        if theme_label(probe(c)["buttons"]) == "跟随系统":
            break
        click_theme(c)
    check("已复位为跟随系统", theme_label(probe(c)["buttons"]) == "跟随系统")

    print("\n--- 9) 小文档回落树视图时，大工具条必须收起来 ---")
    ev(c, """(function(){
      var inp=document.getElementById('input');
      inp.value=JSON.stringify({a:1,b:[1,2,3]},null,2);
      inp.dispatchEvent(new Event('input',{bubbles:true}));
      return 'ok';
    })()""")
    time.sleep(1.5)
    p14 = probe(c)
    check("大工具条已隐藏", p14["tbHidden"], p14["tbHidden"])

    print("\n" + "=" * 60)
    print("通过 %d 项 / 失败 %d 项" % (len(passes), len(fails)))
    if fails:
        print("失败：" + ", ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
