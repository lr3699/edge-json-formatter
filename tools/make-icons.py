#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 JSON Duo 图标：黑底 + 白色「JSON」字标（16/32/48/128/300 全部尺寸）。

方案：SVG 矢量母版（512 viewBox）→ 本地 Edge 渲染 → CDP Page.captureScreenshot
按 clip 逐尺寸截图，直接产出 icons/ 下的成品 PNG，无第三方依赖。

字号的确定方式：先用 fs=100 渲染一次、在页面里量出「JSON」的实际字宽，
再按「目标字宽 / 实测字宽 × 100」反算字号。这样字形比例不会被横向压扁
（对比 lengthAdjust="spacingAndGlyphs" 的强制拉伸），小尺寸下字形更端正。

用法：python tools/make-icons.py --port 9341
"""
import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

# ---------------------------------------------------------------- 设计参数 --
VB = 512                      # viewBox 边长
RADIUS = 112                  # 圆角半径（≈22%，与旧版观感一致）
BG_TOP = "#1C1C1F"            # 黑底：极轻微的上浅下深，给纯黑一点体量感
BG_BOTTOM = "#050506"
FG = "#FFFFFF"
FONT = "'Segoe UI Black','Arial Black','Segoe UI',sans-serif"
TEXT = "JSON"                 # 字标正文
FILL_RATIO = 0.62             # JSON 字宽占版面比例（两侧必须给角括号让出净空）
PROBE_FS = 100                # 测量用字号

# 角括号「」（U+300C / U+300D）用矢量路径画：
#   CJK 字体里的角括号是全角字形、字重与拉丁黑体不匹配，直接排版会把字号压小；
#   路径可精确控制线宽与位置，小尺寸下也不会被抗锯齿磨没。
# 字形按真实字体校正（Microsoft YaHei / SimSun 对照）：
#   「 = 左竖笔 + 顶部横笔向右（开口朝右下）
#   」 = 右竖笔 + 底部横笔向左（开口朝左上）—— 角在下，不是简单水平镜像
BR_W = 34                     # 线宽（512 基准 → 16px 下约 1.1px，落成 1px 实线）
BR_X = 48                     # 竖笔中心 x（离版面边缘约 5%）
BR_ARM = 52                   # 横笔长度（向内伸出）
BR_Y0, BR_Y1 = 196, 318       # 竖笔上下端（中心与字帽带中心对齐）

SIZES = [16, 32, 48, 128, 300]
GAP = 24                      # 排版间距，避免截图 clip 相互沾边


def _corner(right):
    """角括号路径。左「：顶横笔向右、竖笔向下；右」：底横笔向左、竖笔向上。"""
    def X(v):
        return VB - v if right else v

    y_arm = BR_Y1 if right else BR_Y0
    y_end = BR_Y0 if right else BR_Y1
    return "M %.0f %.0f L %.0f %.0f L %.0f %.0f" % (
        X(BR_X + BR_ARM), y_arm, X(BR_X), y_arm, X(BR_X), y_end)


def svg(font_size, baseline):
    """512 viewBox 的图标 SVG（不含外层尺寸属性）。"""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %(vb)d %(vb)d">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="%(top)s"/><stop offset="1" stop-color="%(bot)s"/>'
        '</linearGradient></defs>'
        '<rect width="%(vb)d" height="%(vb)d" rx="%(r)d" fill="url(#bg)"/>'
        '<text x="%(cx).1f" y="%(by).1f" text-anchor="middle" '
        'style="font-family:%(font)s;font-weight:900;font-size:%(fs).2fpx;fill:%(fg)s">'
        '%(text)s</text>'
        '<g fill="none" stroke="%(fg)s" stroke-width="%(bw)d" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="%(bl)s"/><path d="%(br)s"/></g>'
        '</svg>'
        % {"vb": VB, "r": RADIUS, "top": BG_TOP, "bot": BG_BOTTOM,
           "cx": VB / 2, "by": baseline, "font": FONT,
           "fs": font_size, "fg": FG, "text": TEXT,
           "bw": BR_W, "bl": _corner(False), "br": _corner(True)})


def page_with(entries):
    """把若干 (key, size, svg) 绝对定位排开，返回 (html, {key: x})。"""
    parts = ['<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
             'html,body{margin:0;padding:0;background:transparent}</style></head><body>']
    xs, x = {}, 0
    for key, size, code in entries:
        parts.append('<div style="position:absolute;left:%dpx;top:0;width:%dpx;height:%dpx">%s</div>'
                     % (x, size, size, code))
        xs[key] = x
        x += size + GAP
    parts.append("</body></html>")
    return "".join(parts), xs


def ev(client, expr):
    raw = client.evaluate(expr, timeout=60)
    if isinstance(raw, dict):
        raw = raw.get("value", raw)
    return raw


def measure(c):
    """用 Canvas measureText 量字宽与墨迹上下沿（getBBox 给的是行框，含 ascent/descent，
    不能用来居中字形）。返回 (字号, 基线 y)。"""
    html, _ = page_with([("probe", VB, svg(PROBE_FS, VB / 2))])
    tmp = ROOT / "dist" / "_icon-probe.html"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(html, encoding="utf-8")
    c.navigate(tmp.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    js = ("(function(){var cv=document.createElement('canvas');var x=cv.getContext('2d');"
          "x.font='900 %dpx '+%s;var m=x.measureText('%s');"
          "return JSON.stringify({w:m.width,a:m.actualBoundingBoxAscent,"
          "d:m.actualBoundingBoxDescent});})()"
          % (PROBE_FS, json.dumps(FONT), TEXT))
    mt = json.loads(ev(c, js))
    tmp.unlink()
    fs = (VB * FILL_RATIO) / (mt["w"] / PROBE_FS)
    ink_top = mt["a"] / PROBE_FS * fs
    ink_bot = mt["d"] / PROBE_FS * fs
    baseline = (VB - (ink_top + ink_bot)) / 2.0 + ink_top
    print("测量：fs=%d 字宽 %.1f / 墨迹上沿 %.1f 下沿 %.1f → 字号 %.2f，"
          "字高 %.1f（占版面 %.0f%%），基线 %.1f"
          % (PROBE_FS, mt["w"], mt["a"], mt["d"], fs, ink_top + ink_bot,
             100 * (ink_top + ink_bot) / VB, baseline))
    return fs, baseline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9341)
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Page.bringToFront")

    fs, baseline = measure(c)
    code = svg(fs, baseline)

    entries = [("s%d" % size, size, code) for size in SIZES]
    html, xs = page_with(entries)
    tmp = ROOT / "dist" / "_icon-render.html"
    tmp.write_text(html, encoding="utf-8")
    c.navigate(tmp.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    c.send("Page.bringToFront")

    out_dir = ROOT / "icons"
    for size in SIZES:
        res = c.send("Page.captureScreenshot", {
            "format": "png",
            "clip": {"x": xs["s%d" % size], "y": 0, "width": size, "height": size, "scale": 1},
        })
        data = res.get("data")
        if not data:
            print("尺寸 %d 截图失败" % size, file=sys.stderr)
            return 1
        name = "store-icon-300.png" if size == 300 else "icon%d.png" % size
        out = out_dir / name
        out.write_bytes(base64.b64decode(data))
        print("写入 %s（%d 字节）" % (out.relative_to(ROOT), out.stat().st_size))
    tmp.unlink()

    # ------------------------------------------------------------ 预览页 --
    preview = ROOT / "docs" / "icon-redesign"
    preview.mkdir(parents=True, exist_ok=True)

    def cell(size, zoom):
        name = "store-icon-300.png" if size == 300 else "icon%d.png" % size
        return ('<figure><img src="../../icons/%s" width="%d" height="%d" alt="%dpx">'
                '<figcaption>%dpx%s</figcaption></figure>'
                % (name, size * zoom, size * zoom, size, size,
                   "（放大 %dx）" % zoom if zoom > 1 else "实际尺寸"))

    real = "".join(cell(s, 1) for s in SIZES)
    zoomed = "".join(cell(s, 3 if s <= 32 else (2 if s == 48 else 1)) for s in SIZES)
    page = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>JSON Duo 图标重设计预览</title><style>'
            'body{background:#111318;font-family:"Segoe UI",sans-serif;color:#e5e7eb;margin:40px}'
            'h1{font-size:20px;font-weight:600;margin:0 0 8px}'
            'p.sub{color:#9ca3af;font-size:13px;line-height:1.75;max-width:820px;margin:0 0 26px}'
            'h2{font-size:13px;color:#9ca3af;font-weight:500;letter-spacing:.04em;'
            'text-transform:uppercase;margin:34px 0 16px}'
            '.row{display:flex;align-items:flex-end;gap:40px;flex-wrap:wrap;'
            'background:#1b1e26;padding:22px 26px;border-radius:12px}'
            'figure{margin:0}img{display:block;border-radius:8px}'
            'figcaption{margin-top:10px;color:#8b93a3;font-size:12px;text-align:center}'
            '</style></head><body>'
            '<h1>JSON Duo 图标 —— 「JSON」黑底白字</h1>'
            '<p class="sub">黑色圆角底（%s → %s 的极浅渐变，纯黑不至于发死），'
            '白色 Segoe UI Black（回退 Arial Black / Segoe UI）字标，'
            '左右以角括号「」（U+300C / U+300D）夹住。角括号为矢量路径绘制，'
            '线宽固定 %d/512（16px 下约 1px 实线），避免 CJK 全角字形压小字号。'
            'JSON 字宽占版面 %d%%，字号由实测字宽反算，不做横向压缩。</p>'
            '<h2>实际尺寸</h2><div class="row">%s</div>'
            '<h2>放大对照</h2><div class="row">%s</div>'
            '</body></html>' % (BG_TOP, BG_BOTTOM, BR_W, int(FILL_RATIO * 100), real, zoomed))
    (preview / "preview.html").write_text(page, encoding="utf-8")
    print("预览页：%s" % (preview / "preview.html").relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
