#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-compact.py —— 验证大 JSON 下「压缩」切换不再卡顿。

旧实现：压缩走 renderCompactNode 全树重建 DOM，几十万节点一次性插入 → 卡死。
新实现：纯 CSS class 切换（body.jf-compact），DOM 不动。

量法：生成一个节点数可控的大 JSON，载入后测量
  1) 首屏渲染耗时（渲染本身仍分片，应较快）
  2) 点「压缩」→「美化」来回切换的耗时（应 < 50ms，因为只切 class）
  3) 切换后 .jf-row 数量不变（证明没重建 DOM）

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

        # 载入大 JSON（setEditorText 会同步解析 + 分片渲染首屏）
        t0 = time.time()
        client.evaluate(
            "(function(){window.__EDGE_JSON_FORMATTER__.setEditorText(%s);})()"
            % json.dumps(data)
        )
        t1 = time.time()
        print("  载入 + 首屏渲染：%.0f ms" % ((t1 - t0) * 1000), flush=True)
        time.sleep(1.0)

        rows0 = client.evaluate("document.querySelectorAll('.jf-row').length").get("value")
        print("  当前 .jf-row 数量：%s" % rows0, flush=True)

        # 点压缩：按钮文案是「目标动作」语义——pretty 模式显示「美化」（点后变压缩）
        t0 = time.time()
        client.evaluate(
            "(function(){var bs=[].slice.call(document.querySelectorAll('button'));"
            "var b=bs.filter(function(x){return x.textContent.trim()==='美化';})[0];"
            "if(b)b.click();})()"
        )
        t1 = time.time()
        compact_ms = (t1 - t0) * 1000
        time.sleep(0.3)
        rows_compact = client.evaluate("document.querySelectorAll('.jf-row').length").get("value")
        is_compact = client.evaluate(
            "document.querySelector('.jf-body').classList.contains('jf-compact')"
        ).get("value")
        print("  切到压缩：%.0f ms（rows %s -> %s，compact class=%s）"
              % (compact_ms, rows0, rows_compact, is_compact), flush=True)

        # 点美化（切回）：compact 模式下按钮文案是「压缩」
        t0 = time.time()
        client.evaluate(
            "(function(){var bs=[].slice.call(document.querySelectorAll('button'));"
            "var b=bs.filter(function(x){return x.textContent.trim()==='压缩';})[0];"
            "if(b)b.click();})()"
        )
        t1 = time.time()
        pretty_ms = (t1 - t0) * 1000
        is_pretty = client.evaluate(
            "!document.querySelector('.jf-body').classList.contains('jf-compact')"
        ).get("value")
        print("  切回美化：%.0f ms（已切回 pretty=%s）" % (pretty_ms, is_pretty), flush=True)

        check("压缩切换 < 100ms", compact_ms < 100, "%.0fms" % compact_ms)
        check("美化切换 < 100ms", pretty_ms < 100, "%.0fms" % pretty_ms)
        check("压缩态 class 生效", bool(is_compact))
        check("切回美化 class 移除", bool(is_pretty))
        check("DOM 未重建（行数不变）", rows0 == rows_compact, "%s vs %s" % (rows0, rows_compact))

        print("\n结果：%s" % ("全部通过" if not fails else "失败 -> " + ", ".join(fails)))
        return 0 if not fails else 1
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
