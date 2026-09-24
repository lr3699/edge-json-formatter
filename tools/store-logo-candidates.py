#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store-logo-candidates.py —— 生成 300×300 商店 logo 的两个候选并做展示尺寸对照。

背景（2026-09-24）：
    Edge 加载项商店的「Extension logo」是 300×300，但**展示尺寸不是 300**：
    详情页头部约 128px，搜索/分类列表里只有 48~64px。所以判断标准不是「300px 下好不好看」，
    而是「缩到 48~64px 还认不认得出」。本脚本把两个候选按 300 出图，
    再用 NEAREST 缩到商店真实展示尺寸（128/64/48），并排贴出来。

候选：
    A  「JSON」+ 角括号  —— 与扩展 48/128 档一致（两档体系的「大尺寸档」）
    B  加粗单字母 J     —— 与工具栏 16/32 档、站点头部 brand-mark 一致

只读 make-icons.py 的设计参数，不修改它；输出到 docs/publish/。

用法：python tools/store-logo-candidates.py --port 9222
"""
import argparse
import base64
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "publish"


def load_make_icons():
    """把 make-icons.py 当模块加载（文件名带连字符，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("make_icons", ROOT / "tools" / "make-icons.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9222)
    args = ap.parse_args()

    mi = load_make_icons()
    from cdp import CDPClient  # noqa: E402  （路径已由 make-icons 注入）

    OUT.mkdir(parents=True, exist_ok=True)
    SIZE = 300

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    c.send("Page.bringToFront")

    M = mi.measure(c)
    cands = {
        # A：「JSON」+ 角括号（>=48px 档）
        "A_json": mi.svg(mi.marks_for(SIZE, M)),
        # B：加粗单字母 J（小尺寸档强制放大到 300）
        "B_j": mi.svg(mi.marks_for(SIZE, M, force_small=True)),
    }

    entries = [(k, SIZE, code) for k, code in cands.items()]
    html, xs = mi.page_with(entries)
    tmp = ROOT / "dist" / "_logo-cand.html"
    tmp.write_text(html, encoding="utf-8")
    c.navigate(tmp.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    c.send("Page.bringToFront")

    shots = {}
    for k in cands:
        res = c.send("Page.captureScreenshot", {
            "format": "png",
            "clip": {"x": xs[k], "y": 0, "width": SIZE, "height": SIZE, "scale": 1},
        })
        p = OUT / ("logo-cand-%s-300.png" % k)
        p.write_bytes(base64.b64decode(res["data"]))
        shots[k] = p
        print("写入 %s" % p.relative_to(ROOT))
    tmp.unlink()

    # ------------------------------------------------ 展示尺寸对照页 --
    from PIL import Image
    SIZES = [300, 128, 64, 48]
    PAD = 34
    row_h = 300 + 48
    sheet = Image.new("RGB", (PAD * 2 + row_h * len(SIZES), 24 + (row_h + 24) * 2 + 40),
                      (245, 246, 248))
    from PIL import ImageDraw
    dr = ImageDraw.Draw(sheet)
    dr.text((PAD, 10), "300×300 源图 → 商店真实展示尺寸（NEAREST 硬缩，模拟小图观感）",
            fill=(40, 44, 52))
    labels = {"A_json": "A  「JSON」+ 角括号（与扩展 48/128 一致）",
              "B_j": "B  加粗单字母 J（与工具栏 / 站点头部一致）"}
    for i, k in enumerate(["A_json", "B_j"]):
        src = Image.open(shots[k]).convert("RGB").resize((SIZE, SIZE))
        y = 24 + i * (row_h + 24)
        dr.text((PAD, y + 4), labels[k], fill=(60, 66, 76))
        x = PAD
        for s in SIZES:
            im = src.resize((s, s), Image.NEAREST) if s != 300 else src
            sheet.paste(im, (x, y + 22))
            dr.text((x, y + 26 + 300), "%dpx" % s, fill=(120, 126, 136))
            x += 300 + 20
    out = OUT / "store-logo-compare.png"
    sheet.save(out)
    print("对照页：%s" % out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
