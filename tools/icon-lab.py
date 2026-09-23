#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图标小尺寸可读性比稿（icon lab）。

背景：现行图标 16px 下「JSON」四字母实际墨迹仅约 3 物理像素，必然糊成一团。
本脚本在**同一材质**（黑底渐变 + 白色字标）下并列多个「图形语言」概念，
渲染成对照页 + 对照图，供挑选；不写任何线上图标文件。

用法：
    python tools/icon-lab.py --port 9341
"""
import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

# ---------------------------------------------------------------- 设计常量 --
VB = 512
RADIUS = 112
BG_TOP = "#1C1C1F"
BG_BOTTOM = "#050506"
FG = "#FFFFFF"
FONT = "Bahnschrift,'Segoe UI Black','Arial Black',sans-serif"
FW = 700

# 角括号（仅 cur / mono 的大尺寸沿用线上几何）
BR_W, BR_X, BR_ARM = 16, 48, 52
BR_Y0, BR_Y1 = 196, 318
CUR_FILL = 0.62          # 线上「JSON」字宽占版面

PROBE = 100
SIZES = [16, 32, 48, 128]
ZOOM = {16: 8, 32: 4, 48: 2, 128: 1}

# 小尺寸描边加粗量（viewBox 单位）。花括号本身笔画已够重，不能再描边，
# 否则 16px 下两根竖笔会与中钩糊成一块（实测过厚）。细字形（尖括号、字母）才需要补。
def thick_for(size, w16, w32):
    if size <= 20:
        return w16
    if size <= 40:
        return w32
    return 0


def _corner(right):
    def X(v):
        return VB - v if right else v
    y_arm = BR_Y1 if right else BR_Y0
    y_end = BR_Y0 if right else BR_Y1
    return "M %.0f %.0f L %.0f %.0f L %.0f %.0f" % (
        X(BR_X + BR_ARM), y_arm, X(BR_X), y_arm, X(BR_X), y_end)


# ------------------------------------------------------------------ 度量 --
_METRICS = {}


def metrics(client, options):
    """key -> (字宽, 上墨迹, 下墨迹)，均以「字号=1」为单位。"""
    need = [k for k in options if k not in _METRICS]
    if need:
        items = ",".join("['%s',%s]" % (k, json.dumps(t)) for k, t in
                         ((k, options[k]) for k in need))
        js = ("(function(){var cv=document.createElement('canvas');"
              "var x=cv.getContext('2d');var out={};var a=[%s];"
              "for(var i=0;i<a.length;i++){"
              "x.font='%d %dpx '+%s;var m=x.measureText(a[i][1]);"
              "out[a[i][0]]=[m.width/%d,m.actualBoundingBoxAscent/%d,"
              "m.actualBoundingBoxDescent/%d];}return JSON.stringify(out);})()"
              % (items, FW, PROBE, json.dumps(FONT), PROBE, PROBE, PROBE))
        raw = client.evaluate(js, timeout=60)
        if isinstance(raw, dict):
            raw = raw.get("value", raw)
        _METRICS.update(json.loads(raw))
    return {k: _METRICS[k] for k in options}


def fitted(m, target_w=None, target_h=None):
    """按目标字宽/字高反算字号（viewBox 单位）。"""
    fs = 1e9
    if target_w:
        fs = min(fs, target_w / m[0])
    if target_h:
        fs = min(fs, target_h / (m[1] + m[2]))
    return fs


def text_mark(txt, m, fs, stroke=0.0, cx=None, alpha=1.0):
    cx = VB / 2 if cx is None else cx
    baseline = (VB - (m[1] + m[2]) * fs) / 2.0 + m[1] * fs
    s = ('<text x="%.2f" y="%.2f" text-anchor="middle" '
         'style="font-family:%s;font-weight:%d;font-size:%.3fpx;fill:%s;'
         'fill-opacity:%.3f">%s</text>'
         % (cx, baseline, FONT, FW, fs, FG, alpha, txt))
    if stroke:
        s = s.replace('>', ';stroke:%s;stroke-width:%.2f;stroke-linejoin:round;'
                      'paint-order:stroke">' % (FG, stroke), 1)
    return s


def corner_marks():
    return ('<g fill="none" stroke="%s" stroke-width="%d" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="%s"/><path d="%s"/></g>'
            % (FG, BR_W, _corner(False), _corner(True)))


# --------------------------------------------------------------- 概念定义 --
# 每个概念给出 small / big 两档图形语言（small 覆盖 size<=32）
def build(concept, size, M):
    small = size <= 32
    if concept == "cur":                      # 线上现状（对照）
        fs = fitted(M["json"], target_w=CUR_FILL * VB)
        return text_mark("JSON", M["json"], fs) + corner_marks()
    if concept == "brace":
        if small:
            th = thick_for(size, 12, 6)
            fs = fitted(M["brace"], target_h=0.78 * VB, target_w=0.84 * VB)
            return text_mark("{}", M["brace"], fs, stroke=th)
        fs = fitted(M["bjson"], target_w=0.88 * VB)
        return text_mark("{JSON}", M["bjson"], fs, stroke=thick_for(size, 0, 0))
    if concept == "angle":
        if small:
            th = thick_for(size, 28, 14)
            fs = fitted(M["angle"], target_w=0.88 * VB)
            return text_mark("&lt; &gt;", M["angle"], fs, stroke=th)
        fs = fitted(M["bjson"], target_w=0.88 * VB)
        return text_mark("{JSON}", M["bjson"], fs)
    if concept == "mono":
        if small:
            th = thick_for(size, 26, 12)
            fs = fitted(M["j"], target_h=0.74 * VB, target_w=0.66 * VB)
            return text_mark("J", M["j"], fs, stroke=th)
        fs = fitted(M["json"], target_w=CUR_FILL * VB)
        return text_mark("JSON", M["json"], fs) + corner_marks()
    if concept == "bwide":
        if small:
            # 两个花括号分别贴左右边、中间留空。只补一点点笔画——花括号本身已够重，
            # 16px 下描边过多会让两根竖笔与中钩糊成一块（方案 B 的实测结果）。
            fs = fitted(M["lb"], target_h=0.88 * VB)
            w = M["lb"][0] * fs
            cx_l = 0.055 * VB + w / 2
            return (text_mark("{", M["lb"], fs, stroke=thick_for(size, 16, 8), cx=cx_l) +
                    text_mark("}", M["rb"], fs, stroke=thick_for(size, 16, 8), cx=VB - cx_l))
        fs = fitted(M["bjson"], target_w=0.88 * VB)
        return text_mark("{JSON}", M["bjson"], fs)
    if concept == "solo":
        fs = fitted(M["json"], target_h=0.80 * VB, target_w=0.88 * VB)
        return text_mark("JSON", M["json"], fs, stroke=thick_for(size, 26, 12))
    raise KeyError(concept)


CONCEPTS = [
    ("cur", "A · 现状（对照）",
     "各尺寸同一张图：「JSON」+ 角括号。16px 下四字母墨迹仅约 3px，必然糊。"),
    ("brace", "B · 花括号满版",
     "16/32 只留 <b>{ }</b> 一对花括号（无字母、满版、描边加粗）；48px 起改 <b>{JSON}</b>，与 JSON 自身分隔符同源。"),
    ("angle", "C · 尖括号满版",
     "16/32 用 <b>&lt; &gt;</b>——大开口字形最抗缩放；48px 起同样收成 <b>{JSON}</b>。"),
    ("mono", "D · 单字母首字母",
     "16/32 用加粗 <b>J</b> 做主形（笔画可做到 2px 以上，最清晰但语义最弱）；48px 起回到「JSON」+ 角括号。"),
    ("bwide", "E · 花括号分置两侧",
     "16/32 同样用 <b>{ }</b>，但两括号分别贴到左右边、中间留空、不动笔画粗细。"
     "用来验证方案 B 的糊是「间距太近」还是「本来就不成立」。"),
    ("solo", "F · 只放大字号去括号",
     "全线只写 <b>JSON</b>，字号顶到版面 88%、描边加粗。用来验证「不改图形语言、只调参数」到底够不够。"),
]

TILE_COLORS = [
    ("近黑（现行）", "#1C1C1F", "#050506", "#FFFFFF"),
    ("品牌蓝", "#2F6BFF", "#1B4FD8", "#FFFFFF"),
    ("青灰", "#0E7490", "#155E75", "#FFFFFF"),
    ("浅底反白", "#FFFFFF", "#E9EAEE", "#16181D"),
]


# ---------------------------------------------------------------- 页面 --
_UID = [0]


def svg(inner, display_px, tile=None):
    """内联 SVG。渐变 id 必须逐个不同——同页同名 id 会让后出现的图标全部
    复用第一个渐变（配色预览会整片错色）。"""
    _UID[0] += 1
    gid = "g%d" % _UID[0]
    top, bot, fg = tile or (BG_TOP, BG_BOTTOM, FG)
    return ('<svg class="ico" width="%d" height="%d" viewBox="0 0 %d %d" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<defs><linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/>'
            '</linearGradient></defs>'
            '<rect width="%d" height="%d" rx="%d" fill="url(#%s)"/>%s</svg>'
            % (display_px, display_px, VB, VB, gid, top, bot, VB, VB, RADIUS,
               gid, inner.replace(FG, fg)))


def strip(inner, dark, label):
    bg = "#2B2C2F" if dark else "#E8EAEC"
    fgc = "#E8EAED" if dark else "#3C4043"
    return ('<div class="bar" style="background:%s;color:%s">'
            '<span class="slot">%s</span>'
            '<span class="title">JSON Duo · 双栏 JSON 工作台</span>'
            '<span class="x">&#10005;</span></div>'
            % (bg, fgc, svg(inner, 16)))


def cell(inner, size):
    z = ZOOM[size]
    cap = "%dpx" % size + ("（放大 %dx）" % z if z > 1 else "（实际尺寸）")
    return ('<figure><div class="box">%s</div><figcaption>%s</figcaption></figure>'
            % (svg(inner, size * z), cap))


QUICK_CSS = (
    'body{background:#111318;color:#E5E7EB;margin:0;padding:20px 22px 24px;'
    'font-family:"Segoe UI","Microsoft YaHei",sans-serif}'
    'h1{font-size:14px;font-weight:600;margin:0 0 5px}'
    'p.lede{color:#9CA3AF;font-size:11px;line-height:1.7;margin:0 0 16px;max-width:1120px}'
    'p.lede b{color:#E5E7EB}'
    '.qhead{display:flex;align-items:flex-end;gap:12px;margin-bottom:6px;'
    'font-size:10px;color:#8B93A3}'
    '.qhead .h1{width:112px;flex:0 0 112px}.qhead .h2{width:248px;flex:0 0 248px}'
    '.qhead .h3{width:136px;flex:0 0 136px}.qhead .h4{width:136px;flex:0 0 136px}'
    '.qhead .h5{width:196px;flex:0 0 196px}'
    '.qrow{display:flex;align-items:center;gap:12px;margin-bottom:14px}'
    '.qname{width:112px;flex:0 0 112px;font-size:12px;color:#F3F4F6;font-weight:600;'
    'line-height:1.4}'
    '.bar{display:flex;align-items:center;gap:7px;height:29px;padding:0 7px 0 4px;'
    'border-radius:8px 8px 0 0;width:248px;flex:0 0 248px}'
    '.slot{display:flex;align-items:center;justify-content:center;width:20px;height:20px}'
    '.bar .title{font-size:12px;white-space:nowrap;overflow:hidden}'
    '.bar .x{margin-left:auto;font-size:10px;opacity:.55}'
    '.z16{width:136px;flex:0 0 136px;height:136px;display:flex;align-items:center;'
    'justify-content:center}'
    '.z32{width:136px;flex:0 0 136px;height:136px;display:flex;align-items:center;'
    'justify-content:center}'
    '.ladder{width:196px;flex:0 0 196px;display:flex;align-items:flex-end;gap:16px}'
    '.note{font-size:11px;color:#8B93A3;margin:0 0 18px;line-height:1.7}'
)


def quick_page(M):
    """紧凑决策页：一行一个概念，横向排开
    工具栏 16px 实景（浅/深）→ 16px 8× → 32px 4× → 48px → 128px。
    100% 缩放下这一张图就能定案。"""
    rows, heads = [], (
        '<div class="qhead"><div class="h1">方案</div>'
        '<div class="h2">16px 工具栏实景（浅 / 深）</div>'
        '<div class="h3">16px 放大 8×</div><div class="h4">32px 放大 4×</div>'
        '<div class="h5">48px / 128px 实际尺寸</div></div>')
    for cid, name, _ in CONCEPTS:
        m16, m32 = build(cid, 16, M), build(cid, 32, M)
        rows.append(
            '<div class="qrow"><div class="qname">%s</div>'
            '<div class="bar" style="background:#E8EAEC;color:#3C4043">'
            '<span class="slot">%s</span>'
            '<span class="title">JSON Duo · 双栏 JSON 工作台</span>'
            '<span class="x">&#10005;</span></div>'
            '<div class="bar" style="background:#2B2C2F;color:#E8EAED">'
            '<span class="slot">%s</span>'
            '<span class="title">JSON Duo · 双栏 JSON 工作台</span>'
            '<span class="x">&#10005;</span></div>'
            '<div class="z16">%s</div><div class="z32">%s</div>'
            '<div class="ladder">%s%s</div></div>'
            % (name, svg(m16, 16), svg(m16, 16), svg(m16, 128), svg(m32, 128),
               svg(build(cid, 48, M), 48), svg(build(cid, 128, M), 128)))
    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>16px 决策图</title><style>%s</style></head><body>'
            '<h1>JSON Duo 图标 · 小尺寸方案比稿（决策图）</h1>'
            '<p class="lede">前两列是<b>真实尺寸</b>的工具栏模拟（浅色 / 深色主题），'
            '这是唯一的决策依据；后三列只是放大后看轮廓。'
            '判断标准：<b>把图按 100%% 显示时，前两列里能不能一眼分辨出这一枚图标</b>。'
            '五个方案共用完全相同的材质（黑底渐变、白色字标），差异只在图形本身。</p>%s%s'
            '</body></html>' % (QUICK_CSS, heads, "".join(rows)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9341)
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()

    M = metrics(c, {"json": "JSON", "brace": "{}", "bjson": "{JSON}",
                    "angle": "< >", "j": "J", "lb": "{", "rb": "}"})
    for k, v in M.items():
        print("度量 %-6s 字宽 %.3f 上 %.3f 下 %.3f" % (k, v[0], v[1], v[2]))

    rows, ladder = [], []
    for cid, name, desc in CONCEPTS:
        small = build(cid, 16, M)
        bars = (strip(small, False, "浅") + strip(small, True, "深"))
        rows.append('<section class="row"><div class="head"><h3>%s</h3>'
                    '<p>%s</p></div><div class="bars">%s</div>'
                    '<div class="zoom"><figure><div class="box big">%s</div>'
                    '<figcaption>16px 放大 12×（看轮廓是否成立）</figcaption>'
                    '</figure></div></section>'
                    % (name, desc, bars, svg(small, 192)))
        cells = "".join(cell(build(cid, s, M), s) for s in SIZES)
        ladder.append('<section class="row"><div class="head"><h3>%s</h3></div>'
                      '<div class="cells">%s</div></section>' % (name, cells))

    tone_a = "".join(
        '<figure><div class="box">%s</div><figcaption>%s</figcaption></figure>'
        % (svg(build("brace", 16, M), 96, tile=(t, b, f)), label)
        for label, t, b, f in TILE_COLORS)
    tone_b = "".join(
        '<figure><div class="box">%s</div><figcaption>%s</figcaption></figure>'
        % (svg(build("mono", 16, M), 96, tile=(t, b, f)), label)
        for label, t, b, f in TILE_COLORS)

    page = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>JSON Duo 图标 · 16px 可读性比稿</title><style>'
            'body{background:#111318;color:#E5E7EB;margin:0;padding:36px 40px 60px;'
            'font-family:"Segoe UI","Microsoft YaHei",sans-serif}'
            'h1{font-size:20px;font-weight:600;margin:0 0 10px}'
            'p.lede{color:#9CA3AF;font-size:13px;line-height:1.8;max-width:1000px;margin:0 0 34px}'
            'p.lede b{color:#E5E7EB}'
            'h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#9CA3AF;'
            'font-weight:600;margin:40px 0 16px;border-top:1px solid #262A33;padding-top:18px}'
            '.row{display:flex;gap:26px;align-items:flex-start;background:#181B21;'
            'border:1px solid #23272F;border-radius:12px;padding:20px 22px;margin-bottom:14px}'
            '.head{width:270px;flex:0 0 270px}'
            '.head h3{font-size:14px;margin:0 0 8px;color:#F3F4F6;font-weight:600}'
            '.head p{font-size:12px;line-height:1.75;color:#9CA3AF;margin:0}'
            '.head b{color:#E5E7EB}'
            '.bars{display:flex;flex-direction:column;gap:8px}'
            '.bar{display:flex;align-items:center;gap:8px;height:34px;padding:0 8px 0 6px;'
            'border-radius:8px 8px 0 0;width:270px}'
            '.slot{display:flex;align-items:center;justify-content:center;width:22px;height:22px}'
            '.bar .title{font-size:13px;white-space:nowrap}'
            '.bar .x{margin-left:auto;font-size:11px;opacity:.65}'
            '.zoom .box.big{width:192px;height:192px;border-radius:10px;overflow:hidden}'
            '.cells{display:flex;gap:34px;align-items:flex-end}'
            '.box{display:flex;align-items:center;justify-content:center}'
            'figure{margin:0}figcaption{margin-top:9px;font-size:11px;color:#8B93A3;'
            'text-align:center}'
            '</style></head><body>'
            '<h1>JSON Duo 图标 —— 16px 可读性比稿</h1>'
            '<p class="lede">问题不在渲染质量，而在<b>信息密度</b>：16px 方格内「JSON」'
            '四字母的墨迹高度只有约 3 个物理像素、单笔画不足 1 像素，'
            '任何字体都只能糊成一条白线。因此小尺寸必须<b>换图形语言</b>，'
            '而不是继续调字号。下面 5 个概念共用完全相同的材质（黑底渐变、白色字标），'
            '差异只来自图形本身——这样比稿才公平。'
            '<br>看三处即可下判断：<b>①</b> 上方模拟工具栏里的 16px 实景；'
            '<b>②</b> 12× 放大后的轮廓是否还认得出；<b>③</b> 下方尺寸阶梯里 16 与 48 的过渡是否自然。</p>'
            '<h2>① 工具栏 16px 实景（浅色 / 深色主题）</h2>%s'
            '<h2>② 尺寸阶梯（16 / 32 / 48 / 128）</h2>%s'
            '<h2>③ 底板配色（以方案 B 主形为例，16px ×6）</h2>'
            '<div class="row" style="gap:44px">%s</div>'
            '<h2>④ 同上，同一主形换成方案 D 主形</h2>'
            '<div class="row" style="gap:44px">%s</div>'
            '</body></html>'
            % ("".join(rows), "".join(ladder), tone_a, tone_b))

    out_dir = ROOT / "docs" / "icon-redesign"
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [(quick_page(M), "lab-quick.html", [(1, "lab-quick.png"),
                                               (1.25, "lab-quick-125.png")], 1260),
            (page, "lab.html", [(1, "lab.png"), (1.25, "lab-125.png")], 1500)]
    for html, name, shots, vw in jobs:
        tmp = out_dir / name
        tmp.write_text(html, encoding="utf-8")
        for s, png in shots:
            c.send("Emulation.setDeviceMetricsOverride",
                   {"width": vw, "height": 1000, "deviceScaleFactor": s, "mobile": False})
            c.navigate(tmp.as_uri(), timeout=30.0)
            c.wait_for("document.readyState==='complete'", timeout=15)
            c.wait_for("document.fonts.status==='loaded'", timeout=10)
            h = c.evaluate("Math.ceil(document.body.scrollHeight)", timeout=30)
            if isinstance(h, dict):
                h = h.get("value", h)
            c.evaluate("document.body.offsetHeight", timeout=30)
            res = c.send("Page.captureScreenshot", {
                "format": "png", "captureBeyondViewport": True, "fromSurface": True,
                "clip": {"x": 0, "y": 0, "width": vw, "height": int(h), "scale": 1},
            })
            data = res.get("data")
            if not data:
                print("截图失败 %s dsf=%s" % (name, s), file=sys.stderr)
                return 1
            p = out_dir / png
            p.write_bytes(base64.b64decode(data))
            print("写入 %s（%d 字节，%dx%d）"
                  % (p.relative_to(ROOT), p.stat().st_size, int(vw * s), int(h * s)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
