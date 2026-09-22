#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-compact.py —— 验证「压缩 / 美化」切换在虚拟化渲染下依然快且正确。

历史沿革（三次实现，读旧注释时别被误导）：
  ① 最早：压缩走 renderCompactNode 全树重建 DOM，几十万节点一次性插入 → 卡死。
  ② 之后：纯 CSS class 切换（body.jf-compact），DOM 不动，靠 CSS 把嵌套塌缩成一行。
  ③ 现在（树视图虚拟化之后）：CSS 那条路走不通了 —— 扁平行表里只挂着视口那几十行，
     塌缩出来的只会是文档的一小段，语义上已经不成立。改成 render() 重新渲染成
     一段紧凑文本（.jf-ctext）；body.jf-compact 保留，但只作「当前是压缩视图」
     的状态标记，CSS 不再依赖它。

所以本测试现在量的是：
  1) 载入大 JSON 后树视图的行表长度 —— 虚拟化下 DOM 行数恒定，不再是「渐进补齐」，
     所以行数一律从状态栏读（.jf-status 里的「N 行」），它等于行表长度
  2) 点「压缩」的耗时（含一次完整紧凑序列化；走原生路径，几万节点几十毫秒）
  3) 压缩态：渲染出 .jf-ctext、树行为 0、文本解析回来与原文完全等价
  4) 切回美化：行表长度完全还原（一条都不能少）—— 这是「压缩视图别把行表弄丢」的回归点

用法：python tools/test-compact.py [--url ...] [--port 9222] [--nodes 20000]
"""

import argparse
import json
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient, CDPError  # noqa: E402

# 从状态栏读行表长度。虚拟化的树里 DOM 只有几十行，只有这个数是真的文档行数。
STATUS_ROWS = (
    "(function(){var s=document.querySelector('.jf-status');"
    "if(!s)return null;var m=s.textContent.match(/([\\d,]+)\\s*行/);"
    "return m?parseInt(m[1].replace(/,/g,''),10):null;})()"
)

# 在工具栏里找文案为 label 的按钮并点击。必须限定 .jf-toolbar：
# 输入面板上也有个「压缩」按钮（那是对源文本做压缩，不是切输出排版），不限定会点错。
CLICK_TOOLBAR = (
    "(function(){var bs=[].slice.call(document.querySelectorAll('.jf-toolbar button'));"
    "var b=bs.filter(function(x){return x.textContent.trim()===%s;})[0];"
    "if(!b)return false;b.click();return true;})()"
)


def gen_json(n_nodes):
    """生成约 n_nodes 个节点的嵌套 JSON（对象数组 + 内嵌对象）。"""
    items = []
    for i in range(n_nodes // 5):
        items.append({
            "id": i,
            "name": "item-%d" % i,
            "active": i % 2 == 0,
            "tags": ["a", "b", "c"],
            "meta": {"orderId": "6006538365075169%d" % (i % 10), "score": i * 1.5},
        })
    return {"total": len(items), "items": items}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18544/app.html")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--nodes", type=int, default=20000)
    args = p.parse_args(argv)

    data = json.dumps(gen_json(args.nodes))
    print("生成 JSON：%s 字符" % len(data), flush=True)

    fails = []

    def check(name, cond, extra=""):
        if not cond:
            fails.append(name)
        print("  [%s] %-26s %s" % ("PASS" if cond else "FAIL", name, extra))

    client = CDPClient(host="127.0.0.1", port=args.port, timeout=120)
    try:
        client.ensure_page()
        client.send("Page.enable")
        client.navigate(args.url, timeout=30)
        time.sleep(3)

        # 载入大 JSON（setEditorText 会同步解析 + 建行表 + 画首屏窗口）
        t0 = time.time()
        client.evaluate(
            "(function(){window.__EDGE_JSON_FORMATTER__.setEditorText(%s);})()"
            % json.dumps(data)
        )
        t1 = time.time()
        print("  载入 + 首屏渲染：%.0f ms" % ((t1 - t0) * 1000), flush=True)
        time.sleep(0.4)

        rows0 = client.evaluate(STATUS_ROWS).get("value")
        dom0 = client.evaluate("document.querySelectorAll('.jf-row').length").get("value")
        print("  行表长度（状态栏）：%s，DOM 行数：%s" % (rows0, dom0), flush=True)
        check("状态栏能读出行表长度", isinstance(rows0, int) and rows0 > 0, rows0)
        check("虚拟化：DOM 行数远小于行表长度", isinstance(dom0, int) and dom0 < 200,
              "dom=%s rows=%s" % (dom0, rows0))

        # 点「美化」按钮 → 切到压缩（工具栏按钮文案是「当前状态」语义：
        # pretty 时显示「美化」，compact 时显示「压缩」）
        t0 = time.time()
        clicked = client.evaluate(CLICK_TOOLBAR % json.dumps("美化")).get("value")
        t1 = time.time()
        compact_ms = (t1 - t0) * 1000
        time.sleep(0.3)
        is_compact = client.evaluate(
            "document.querySelector('.jf-body').classList.contains('jf-compact')"
        ).get("value")
        ctext_len = client.evaluate(
            "(function(){var c=document.querySelector('.jf-ctext');"
            "return c?c.textContent.length:-1;})()"
        ).get("value")
        dom_compact = client.evaluate("document.querySelectorAll('.jf-row').length").get("value")
        # 压缩文本的正确性：解析回来必须和原对象完全等价（比字符串比对稳，
        # 不受两侧各自序列化细节影响，但仍能证明「捏出来的是一份合法且等价的 JSON」）
        # 注意末尾的 () —— 漏了它整个表达式会求值成一个函数对象（CDP 只能拿到 {}），
        # 断言就会「静默地」永远是 false。
        same = client.evaluate(
            "(function(){var c=document.querySelector('.jf-ctext');"
            "if(!c)return false;"
            "try{return JSON.stringify(JSON.parse(c.textContent))===JSON.stringify(JSON.parse(%s));}"
            "catch(e){return false;}})()"
            % json.dumps(data)
        ).get("value")
        print("  切到压缩：%.0f ms（ctext=%s 字符，DOM 树行 %s，compact class=%s）"
              % (compact_ms, ctext_len, dom_compact, is_compact), flush=True)

        check("工具栏「美化」按钮可点", bool(clicked))
        check("压缩切换 < 200ms", compact_ms < 200, "%.0fms" % compact_ms)
        check("压缩态 class 生效", bool(is_compact))
        check("压缩态渲染出紧凑文本", isinstance(ctext_len, int) and ctext_len > 1000, ctext_len)
        check("压缩态没有树行", dom_compact == 0, dom_compact)
        check("紧凑文本与原文等价", bool(same))

        # 点「压缩」按钮 → 切回美化
        t0 = time.time()
        client.evaluate(CLICK_TOOLBAR % json.dumps("压缩"))
        t1 = time.time()
        pretty_ms = (t1 - t0) * 1000
        time.sleep(0.4)
        is_pretty = client.evaluate(
            "!document.querySelector('.jf-body').classList.contains('jf-compact')"
        ).get("value")
        rows_back = client.evaluate(STATUS_ROWS).get("value")
        print("  切回美化：%.0f ms（行表 %s -> %s，pretty=%s）"
              % (pretty_ms, rows0, rows_back, is_pretty), flush=True)

        check("美化切换 < 200ms", pretty_ms < 200, "%.0fms" % pretty_ms)
        check("切回美化 class 移除", bool(is_pretty))
        check("切回美化后行表一条不少", rows_back == rows0, "%s vs %s" % (rows0, rows_back))
        check("切回美化后树行为窗口大小", 0 < client.evaluate(
            "document.querySelectorAll('.jf-row').length").get("value") < 200)

        print("\n结果：%s" % ("全部通过" if not fails else "失败 -> " + ", ".join(fails)))
        return 0 if not fails else 1
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
