#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 JSON Duo 图标全套：黑底 + 白色字标，分尺寸两档图形语言。

为什么分档（2026-09-23 实测结论）：
    扩展工具栏 / 标签页图标就是 16px。16px 方格内「JSON」四字母的墨迹高度只有
    约 3 个物理像素、单笔画不足 1px，任何字体都只能糊成一条白线；角括号 16/512 的
    线宽在 16px 下仅 0.5px，被抗锯齿磨没。根因是信息密度，调字号无解。
    → **16/32 改用一对花括号「{ }」分置左右边做主形；48px 起才用完整字标「JSON」+ 角括号。**

方案：SVG 矢量母版（512 viewBox）→ 本地 Edge 渲染 → CDP Page.captureScreenshot
按 clip 逐尺寸截图，直接产出 icons/ 下的成品 PNG，无第三方依赖。

字号的确定方式：先量出字形的墨迹度量（Canvas measureText 的 width /
actualBoundingBoxAscent|Descent），再按目标字宽/字高反算字号。这样字形比例不会被
横向压扁，小尺寸下字形更端正。注意 getBBox 给的是行框（含 ascent/descent），
不能用来居中字形。

用法：python tools/make-icons.py --port 9341
"""
import argparse
import base64
import json
import shutil
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
# 字体：Bahnschrift Bold —— 几何无衬线（DIN 系），字形干净、笔画粗细与细角括号协调，
# 同宽下字高比 Segoe UI Black 更饱满（19% vs 17%）。回退链覆盖非 Windows 环境。
# 注：字体只在生成阶段使用，成品 PNG 不含字体依赖。
FONT = "Bahnschrift,'Segoe UI Black','Arial Black',sans-serif"
FONT_WEIGHT = 700

BIG_TEXT = "JSON"             # 大尺寸字标正文（48px 起）
BIG_FILL = 0.62               # 大尺寸「JSON」字宽占版面比例（两侧须给角括号让净空）
# 小尺寸主形（16 / 32px）——**方案 E**：一对花括号分置左右边、中间留空。
# 花括号自身笔画重、开口大，分置后两根竖笔互不干扰，16px 下仍读得出「{ }」；
# 且它就是 JSON 的语法符号，语义比单字母强（单字母那版是方案 D）。
SMALL_BRACE_H = 0.88          # 花括号墨迹高度占版面比例
SMALL_BRACE_X = 0.055         # 左括号左边缘距版面边缘（占版面比例）
SMALL_THRESHOLD = 32          # ≤ 此尺寸走小尺寸主形
PROBE_FS = 100                # 测量用字号

# 小尺寸描边量（viewBox 单位）：只补一点点。
# **切勿给花括号补大描边**——≥40/512 时两根竖笔会与中钩粘连成一块白（方案 B 的实测结论）。
SMALL_STROKE = {16: 16, 32: 8}

# 角括号「」（U+300C / U+300D）用矢量路径画：
#   CJK 字体里的角括号是全角字形、字重与拉丁黑体不匹配，直接排版会把字号压小；
#   路径可精确控制线宽与位置，小尺寸下也不会被抗锯齿磨没。
# 字形按真实字体校正（Microsoft YaHei / SimSun 对照）：
#   「 = 左竖笔 + 顶部横笔向右（开口朝右下）
#   」 = 右竖笔 + 底部横笔向左（开口朝左上）——角在下，不是简单水平镜像
BR_W = 16                     # 线宽：与 Bahnschrift Bold 的字母笔画等重（≈0.12em）
BR_X = 48                     # 竖笔中心 x（离版面边缘约 5%）
BR_ARM = 52                   # 横笔长度（向内伸出）
BR_Y0, BR_Y1 = 196, 318       # 竖笔上下端（中心与字帽带中心对齐）

SIZES = [16, 32, 48, 128, 300]
SITE_FAVICON_SIZE = 128       # 站点 favicon 的出图边长（浏览器再按需缩到 16/24）
# favicon 的描边量单独指定：它虽以 128px 出图，但实际显示在 16px（标签页）与
# 24px（站点头部），所以取 16px 档的描边量，缩放后与工具栏里的 icon16 等重。
# 若沿用按出图尺寸取值的规则，128px 会落到 0，标签页上会明显偏细。
SITE_FAVICON_STROKE = SMALL_STROKE[16]
GAP = 24                      # 排版间距，避免截图 clip 相互沾边


def _corner(right):
    """角括号路径。左「：顶横笔向右、竖笔向下；右」：底横笔向左、竖笔向上。"""
    def X(v):
        return VB - v if right else v

    y_arm = BR_Y1 if right else BR_Y0
    y_end = BR_Y0 if right else BR_Y1
    return "M %.0f %.0f L %.0f %.0f L %.0f %.0f" % (
        X(BR_X + BR_ARM), y_arm, X(BR_X), y_arm, X(BR_X), y_end)


def marks_for(size, M, force_small=None, stroke=None):
    """按尺寸档返回图形标记（512 坐标系内的 SVG 片段）。

    force_small 用来强制走小尺寸字形——站点 favicon 就靠它：
    favicon 在标签页里被浏览器缩到 16px 显示，必须用**小尺寸字形**，
    否则等于把「JSON」版直接缩下去，照样糊（这正是用户最初看到的问题）。

    stroke 覆盖默认描边量（viewBox 单位）。仅 favicon 需要——它以 128px 出图、
    却显示在 16/24px，按出图尺寸取值会偏细。
    """
    small = (size <= SMALL_THRESHOLD) if force_small is None else force_small
    if small:
        # 方案 E：两个花括号贴上左右边、中间留空。字号由**花括号自己的墨迹高**反算
        # （不是字母的），左右括号共用同一份度量，字号与基线才严格一致——
        # 「{」「}」虽是镜像字形，各取各的度量一旦有差就会上下错位。
        a_per, d_per = M["lb"][1], M["lb"][2]
        fs = SMALL_BRACE_H * VB / (a_per + d_per)
        cx = SMALL_BRACE_X * VB + M["lb"][0] * fs / 2
        stroke = SMALL_STROKE.get(size, 0) if stroke is None else stroke
        baseline = (VB - (a_per + d_per) * fs) / 2.0 + a_per * fs
        tpl = ('<text x="%.2f" y="%.2f" text-anchor="middle" '
               'style="font-family:%s;font-weight:%d;font-size:%.3fpx;fill:%s;'
               'stroke:%s;stroke-width:%d;paint-order:stroke;stroke-linejoin:round">'
               '%s</text>')
        style = (FONT, FONT_WEIGHT, fs, FG, FG, stroke)
        return (tpl % ((cx, baseline) + style + ("{",)) +
                tpl % ((VB - cx, baseline) + style + ("}",)))
    m = M["big"]
    fs = BIG_FILL * VB / m[0]
    baseline = (VB - (m[1] + m[2]) * fs) / 2.0 + m[1] * fs
    return ('<text x="%.1f" y="%.2f" text-anchor="middle" '
            'style="font-family:%s;font-weight:%d;font-size:%.3fpx;fill:%s">%s</text>'
            '<g fill="none" stroke="%s" stroke-width="%d" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="%s"/><path d="%s"/></g>'
            % (VB / 2, baseline, FONT, FONT_WEIGHT, fs, FG, BIG_TEXT,
               FG, BR_W, _corner(False), _corner(True)))


def svg(inner):
    """512 viewBox 的图标 SVG（不含外层尺寸属性）。"""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %(vb)d %(vb)d">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="%(top)s"/><stop offset="1" stop-color="%(bot)s"/>'
        '</linearGradient></defs>'
        '<rect width="%(vb)d" height="%(vb)d" rx="%(r)d" fill="url(#bg)"/>%(inner)s'
        '</svg>'
        % {"vb": VB, "r": RADIUS, "top": BG_TOP, "bot": BG_BOTTOM, "inner": inner})


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
    """量字形墨迹（以「字号=1」为单位）。返回 {'big': ..., 'lb': ..., 'rb': ...}。"""
    tmp = ROOT / "dist" / "_icon-probe.html"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text('<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
                   '<body></body></html>', encoding="utf-8")
    c.navigate(tmp.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    texts = [BIG_TEXT, "{", "}"]
    js = ("(function(){var cv=document.createElement('canvas');var x=cv.getContext('2d');"
          "x.font='%d %dpx '+%s;var out={};%s.forEach(function(t){"
          "var m=x.measureText(t);out[t]=[m.width/%d,m.actualBoundingBoxAscent/%d,"
          "m.actualBoundingBoxDescent/%d];});return JSON.stringify(out);})()"
          % (FONT_WEIGHT, PROBE_FS, json.dumps(FONT), json.dumps(texts),
             PROBE_FS, PROBE_FS, PROBE_FS))
    mt = json.loads(ev(c, js))
    tmp.unlink()
    out = {"big": mt[BIG_TEXT], "lb": mt["{"], "rb": mt["}"]}
    for k, label in (("big", BIG_TEXT), ("lb", "{"), ("rb", "}")):
        v = out[k]
        print("度量 %-4s %-5s 字宽 %.3f 墨迹上 %.3f 下 %.3f" % (k, label, v[0], v[1], v[2]))
    return out


APPLIED_CSS = (
    'body{background:#111318;color:#E5E7EB;margin:0;padding:22px 26px 26px;'
    'font-family:"Segoe UI","Microsoft YaHei",sans-serif}'
    'h1{font-size:14px;font-weight:600;margin:0 0 5px}'
    'p.lede{color:#9CA3AF;font-size:11px;line-height:1.7;margin:0 0 18px;max-width:1000px}'
    'p.lede b{color:#E5E7EB}'
    '.row{display:flex;align-items:center;gap:14px;margin-bottom:13px}'
    '.tag{width:150px;flex:0 0 150px;font-size:12px;font-weight:600;color:#F3F4F6;'
    'line-height:1.45}'
    '.tag em{display:block;font-style:normal;font-size:10px;color:#8B93A3;font-weight:400}'
    '.bar{display:flex;align-items:center;gap:7px;height:29px;padding:0 7px 0 4px;'
    'border-radius:8px 8px 0 0;width:250px;flex:0 0 250px}'
    '.slot{display:flex;align-items:center;justify-content:center;width:20px;height:20px}'
    '.bar .title{font-size:12px;white-space:nowrap;overflow:hidden}'
    '.bar .x{margin-left:auto;font-size:10px;opacity:.55}'
    '.zoom{width:128px;flex:0 0 128px;height:128px;display:flex;align-items:center;'
    'justify-content:center}'
    '.ladder{display:flex;align-items:flex-end;gap:16px}'
    '.cap{font-size:10px;color:#8B93A3;margin-top:6px;text-align:center}'
    '.sizes{display:flex;align-items:flex-start;gap:34px}'
    '.split{border-top:1px solid #262A33;margin:20px 0 16px}'
)


def applied_page(pairs, fav_rows):
    """改前 / 改后实尺寸对照页。

    pairs    = [(标签, 说明, {size: 相对路径})]      —— 扩展图标（16/32/48/128/300）
    fav_rows = [(标签, 说明, 相对路径)]              —— 站点 favicon（128px 源，缩到 16/24 看）
    """
    rows = []
    for label, note, src in pairs:
        imgs = '<span class="slot"><img src="%s" width="16" height="16" alt=""></span>' % src["16"]
        rows.append(
            '<div class="row"><div class="tag">%s<em>%s</em></div>'
            '<div class="bar" style="background:#E8EAEC;color:#3C4043">%s'
            '<span class="title">JSON Duo · 双栏 JSON 工作台</span>'
            '<span class="x">&#10005;</span></div>'
            '<div class="bar" style="background:#2B2C2F;color:#E8EAED">%s'
            '<span class="title">JSON Duo · 双栏 JSON 工作台</span>'
            '<span class="x">&#10005;</span></div>'
            '<div class="zoom"><img src="%s" width="128" height="128" alt=""></div>'
            '<div class="ladder">%s</div></div>'
            % (label, note, imgs, imgs, src["16"],
               "".join('<img src="%s" width="%d" height="%d" alt="">' % (src[str(s)], s, s)
                       for s in (32, 48, 128) if str(s) in src)))
    fav = []
    for label, note, src in fav_rows:
        fav.append(
            '<div class="row"><div class="tag">%s<em>%s</em></div>'
            '<div class="bar" style="background:#E8EAEC;color:#3C4043">'
            '<span class="slot"><img src="%s" width="16" height="16" alt=""></span>'
            '<span class="title">JSON Duo · 双栏 JSON 工作台</span>'
            '<span class="x">&#10005;</span></div>'
            '<div class="bar" style="background:#2B2C2F;color:#E8EAED">'
            '<span class="slot"><img src="%s" width="16" height="16" alt=""></span>'
            '<span class="title">JSON Duo · 双栏 JSON 工作台</span>'
            '<span class="x">&#10005;</span></div>'
            '<div class="zoom"><img src="%s" width="96" height="96" alt=""></div>'
            '<div class="sizes">'
            '<div><img src="%s" width="24" height="24" alt=""><div class="cap">24px 站点头部</div></div>'
            '<div><img src="%s" width="16" height="16" alt=""><div class="cap">16px 标签页</div></div>'
            '</div></div>' % (label, note, src, src, src, src, src))
    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>JSON Duo 图标 · 改前改后</title><style>%s</style></head><body>'
            '<h1>JSON Duo 图标 · 改前 / 改后（真实尺寸）</h1>'
            '<p class="lede">前两条是<b>真实尺寸</b>的 16px 工具栏实景（浅色 / 深色主题），'
            '这是唯一的判断依据；后面是 16px 放大 8 倍与 32 / 48 / 128 的实际尺寸。'
            '改后：<b>16/32px 换成一对花括号 { }（分置左右边、中间留空）</b>'
            '（四字母在此尺寸墨迹仅约 3 物理像素，必然糊），'
            '48px 起保持完整字标 <b>「JSON」</b> + 角括号，品牌观感延续。</p>%s'
            '<div class="split"></div>'
            '<h1>站点 favicon（浏览器把 128px 源缩到 16 / 24px 显示）</h1>'
            '<p class="lede">标签页里那枚小图标吃的就是 favicon，所以它必须用<b>小尺寸字形</b>；'
            '拿「JSON」版直接缩下去，结果与改前一样糊。</p>%s'
            '</body></html>'
            % (APPLIED_CSS, "".join(rows), "".join(fav)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9341)
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    # 关键：本机显示缩放 125% 会让截图放大 1.25 倍（128 的图标截出 160px）。
    # 锁定 deviceScaleFactor=1，CSS 像素 == 设备像素，产出尺寸才与声明一致
    # —— 商店图标必须是精确的 300×300，否则会被拒。
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1400, "height": 800, "deviceScaleFactor": 1, "mobile": False})
    c.send("Page.bringToFront")

    out_dir = ROOT / "icons"
    docs = ROOT / "docs" / "icon-redesign"
    docs.mkdir(parents=True, exist_ok=True)
    prev = docs / "prev"
    prev.mkdir(exist_ok=True)
    # 覆盖前先留一份旧图，供「改前/改后」对照页引用（仓库历史里也有，双保险）。
    # **只在文件不存在时写** —— prev/ 是「改前（1.1.7 线上）」的冻结基线，
    # 每次运行都刷的话，跑第二遍就会把基线也刷成新版，对照页随即失效。
    for size in SIZES:
        name = "store-icon-300.png" if size == 300 else "icon%d.png" % size
        if (out_dir / name).exists() and not (prev / name).exists():
            shutil.copy2(out_dir / name, prev / name)

    M = measure(c)
    codes = {size: svg(marks_for(size, M)) for size in SIZES}
    # 站点 favicon：**强制小尺寸字形**。标签页把 favicon 缩到 16px 显示，
    # 若直接拿大尺寸版（「JSON」）去缩，结果与改前一样糊。
    fav_code = svg(marks_for(SITE_FAVICON_SIZE, M, force_small=True,
                             stroke=SITE_FAVICON_STROKE))

    entries = [("s%d" % size, size, codes[size]) for size in SIZES]
    entries.append(("fav", SITE_FAVICON_SIZE, fav_code))
    html, xs = page_with(entries)
    tmp = ROOT / "dist" / "_icon-render.html"
    tmp.write_text(html, encoding="utf-8")
    c.navigate(tmp.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    c.send("Page.bringToFront")

    def shot(key, size, out, label):
        res = c.send("Page.captureScreenshot", {
            "format": "png",
            "clip": {"x": xs[key], "y": 0, "width": size, "height": size, "scale": 1},
        })
        data = res.get("data")
        if not data:
            print("%s 截图失败" % label, file=sys.stderr)
            return False
        out.write_bytes(base64.b64decode(data))
        print("写入 %s（%d 字节）" % (out.relative_to(ROOT), out.stat().st_size))
        return True

    for size in SIZES:
        name = "store-icon-300.png" if size == 300 else "icon%d.png" % size
        if not shot("s%d" % size, size, out_dir / name, "尺寸 %d" % size):
            return 1
    tmp.unlink()

    site_dir = ROOT / "site"
    if site_dir.is_dir():
        if not shot("fav", SITE_FAVICON_SIZE, site_dir / "favicon.png", "站点 favicon"):
            return 1

    # ------------------------------------------------------------ 预览页 --
    def cell(size, zoom):
        name = "store-icon-300.png" if size == 300 else "icon%d.png" % size
        return ('<figure><img src="../../icons/%s" width="%d" height="%d" alt="%dpx">'
                '<figcaption>%dpx%s</figcaption></figure>'
                % (name, size * zoom, size * zoom, size, size,
                   "（放大 %dx）" % zoom if zoom > 1 else "实际尺寸"))

    real = "".join(cell(s, 1) for s in SIZES)
    zoomed = "".join(cell(s, 3 if s <= 32 else (2 if s == 48 else 1)) for s in SIZES)
    page = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>JSON Duo 图标预览</title><style>'
            'body{background:#111318;font-family:"Segoe UI",sans-serif;color:#e5e7eb;margin:40px}'
            'h1{font-size:20px;font-weight:600;margin:0 0 8px}'
            'p.sub{color:#9ca3af;font-size:13px;line-height:1.75;max-width:860px;margin:0 0 26px}'
            'h2{font-size:13px;color:#9ca3af;font-weight:500;letter-spacing:.04em;'
            'text-transform:uppercase;margin:34px 0 16px}'
            '.row{display:flex;align-items:flex-end;gap:40px;flex-wrap:wrap;'
            'background:#1b1e26;padding:22px 26px;border-radius:12px}'
            'figure{margin:0}img{display:block;border-radius:8px;image-rendering:auto}'
            'figcaption{margin-top:10px;color:#8b93a3;font-size:12px;text-align:center}'
            '</style></head><body>'
            '<h1>JSON Duo 图标 —— 分尺寸两档图形语言</h1>'
            '<p class="sub">黑色圆角底（%s → %s 的极浅渐变，纯黑不至于发死）。'
            '<b>16px / 32px</b> 用一对花括号 <b>{ }</b>（墨迹高 %.0f%% 版面，分置左右边、'
            '中间留空、只补极少描边）——四字母字标在 16px 下'
            '墨迹仅约 3 物理像素、单笔画不足 1px，任何字体都会糊成一条白线，故小尺寸换形。'
            '<b>48px 起</b>用完整字标「%s」（字宽占版面 %d%%），左右以角括号「」夹住；'
            '角括号为矢量路径绘制，线宽固定 %d/512，与字母笔画等重'
            '（CJK 全角字形会压小字号，故不直接用字形）；'
            '右括号横笔在底部（角朝右下），按 Microsoft YaHei / SimSun 真实字形校正。</p>'
            '<h2>实际尺寸</h2><div class="row">%s</div>'
            '<h2>放大对照</h2><div class="row">%s</div>'
            '</body></html>'
            % (BG_TOP, BG_BOTTOM, SMALL_BRACE_H * 100, BIG_TEXT,
               int(BIG_FILL * 100), BR_W, real, zoomed))
    (docs / "preview.html").write_text(page, encoding="utf-8")
    print("预览页：%s" % (docs / "preview.html").relative_to(ROOT))

    # ---------------------------------------------------- 改前 / 改后页 --
    old = {str(s): "prev/%s" % ("store-icon-300.png" if s == 300 else "icon%d.png" % s)
           for s in SIZES}
    new = {str(s): "../../icons/%s" % ("store-icon-300.png" if s == 300 else "icon%d.png" % s)
           for s in SIZES}
    ap_html = applied_page(
        [("改前（1.1.7 线上）", "16px 四字母「JSON」", old),
         ("改后（方案 E）", "16px 花括号 { } 分置两侧", new)],
        [("改前 favicon", "128px 的「JSON」版", "prev/icon128.png"),
         ("改后 favicon", "128px 的小尺寸字形版", "../../site/favicon.png")])
    (docs / "applied.html").write_text(ap_html, encoding="utf-8")
    c.navigate((docs / "applied.html").as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    c.wait_for("document.fonts.status==='loaded'", timeout=10)
    h = c.evaluate("Math.ceil(document.body.scrollHeight)", timeout=30)
    if isinstance(h, dict):
        h = h.get("value", h)
    res = c.send("Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": True, "fromSurface": True,
        "clip": {"x": 0, "y": 0, "width": 1160, "height": int(h), "scale": 1}})
    if res.get("data"):
        (docs / "applied.png").write_bytes(base64.b64decode(res["data"]))
        print("改前改后：%s" % (docs / "applied.png").relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
