#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-compact.py —— 「压缩 / 美化」输出切换下线后的回归（2026-10-19 功能精简）。

原职能：验证右侧工具条「美化 ⇄ 压缩」切换在虚拟化渲染下依然快且正确。
现职能：该按钮已按「功能精简」移除，右栏输出恒为美化（缩进展开）；要单行文本
请用左栏「压缩」按钮（对源文本做压缩，回灌后重新排版）。本测试守住新契约：

  1) 右侧工具条**不存在**「压缩 / 美化」按钮（入口不许悄悄回来）
  2) body 无 jf-compact 状态类、页面上没有 .jf-ctext 紧凑文本节点
  3) 树视图照常渲染：行表长度可读、DOM 行数受虚拟化控制
  4) 左栏「压缩」按钮仍可用：点完源文本去掉所有换行（能力没被一起删掉），
     且压缩后树视图依然渲染得出来

内部机制备注：viewer.js 的 outMode / renderCompactText() 代码保留，
state.outMode 恒为 'pretty'，只是不再有 UI 入口。

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

# 右侧树视图工具条里文案为 label 的按钮（限定 .jf-toolbar：输入面板上也有个
# 「压缩」按钮，那是对源文本做压缩，不是切输出排版，不限定会点错/找错）。
TOOLBAR_BTN = (
    "(function(){var bs=[].slice.call(document.querySelectorAll('.jf-toolbar button'));"
    "var b=bs.filter(function(x){return x.textContent.trim()===%s;})[0];"
    "return b?true:false;})()"
)

# 左栏「压缩」按钮（输入面板那个，id 选择器不会和右侧工具条搞混）
CLICK_MINIFY = "document.getElementById('btnMinify').click()"


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
    p.add_argument("--url", default="http://127.0.0.1:18544/site/app.html")
    p.add_argument("--port", type=int, default=9222)
    # 注意：≥600KB 的文档会自动走全文视图（bigview），树上什么都没有 ——
    # 本测试验的是树视图契约，夹具必须留在树视图里。2000 项 ≈ 460KB。
    p.add_argument("--nodes", type=int, default=10000)
    args = p.parse_args(argv)

    # 故意用缩进版：否则紧凑 JSON 本来就没有换行，「去掉所有换行」会空转成恒真
    data = json.dumps(gen_json(args.nodes), indent=2)
    print("生成 JSON：%s 字符（缩进版，%d 行）"
          % (len(data), data.count("\n") + 1), flush=True)

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

        # 视图守卫：≥600KB 会自动切全文视图（bigview），树上什么都没有。
        # 夹具超阈值时后面所有树视图断言都会变成假失败，先拦一道。
        in_big = client.evaluate(
            "(function(){return !!document.querySelector('.cm-editor') ||"
            " !document.querySelector('.jf-body');})()"
        ).get("value")
        check("夹具留在树视图（未触达 600KB 全文视图阈值）", not in_big,
              "len=%d，超阈值请减小 --nodes" % len(data))

        rows0 = client.evaluate(STATUS_ROWS).get("value")
        dom0 = client.evaluate("document.querySelectorAll('.jf-row').length").get("value")
        print("  行表长度（状态栏）：%s，DOM 行数：%s" % (rows0, dom0), flush=True)
        check("状态栏能读出行表长度", isinstance(rows0, int) and rows0 > 0, rows0)
        check("虚拟化：DOM 行数远小于行表长度", isinstance(dom0, int) and dom0 < 200,
              "dom=%s rows=%s" % (dom0, rows0))

        # --- 新契约一：右侧工具条不再有「压缩 / 美化」按钮 ---
        has_mode = client.evaluate(TOOLBAR_BTN % json.dumps("美化")).get("value") or \
            client.evaluate(TOOLBAR_BTN % json.dumps("压缩")).get("value")
        check("工具条没有「美化」按钮", not has_mode)

        # --- 新契约二：输出恒为美化（无紧凑态） ---
        is_compact = client.evaluate(
            "(function(){var b=document.querySelector('.jf-body');"
            "return b?b.classList.contains('jf-compact'):null;})()"
        ).get("value")
        ctext = client.evaluate(
            "(function(){var c=document.querySelector('.jf-ctext');"
            "return c?c.textContent.length:-1;})()"
        ).get("value")
        check("body 无 jf-compact 状态类", not is_compact)
        check("没有 .jf-ctext 紧凑文本节点", ctext == -1, ctext)

        # --- 新契约三：左栏「压缩」按钮仍然可用（能力没被一起删掉） ---
        client.evaluate(CLICK_MINIFY)
        time.sleep(0.6)
        v = client.evaluate(
            "window.__EDGE_JSON_FORMATTER__.getEditorText ?"
            " window.__EDGE_JSON_FORMATTER__.getEditorText() : ''"
        ).get("value") or ""
        check("左栏压缩：源文本去掉所有换行", "\n" not in v, "len=%d" % len(v))
        rows_after = client.evaluate(STATUS_ROWS).get("value")
        check("压缩后树视图仍渲染", isinstance(rows_after, int) and rows_after > 0, rows_after)

        print("\n结果：%s" % ("全部通过" if not fails else "失败 -> " + ", ".join(fails)))
        return 0 if not fails else 1
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
