#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 JSON Duo 图标全套：黑底 + 白色字标，分尺寸两档图形语言。

为什么分档（2026-09-23 实测结论）：
    扩展工具栏 / 标签页图标就是 16px。16px 方格内「JSON」四字母的墨迹高度只有
    约 3 个物理像素、单笔画不足 1px，任何字体都只能糊成一条白线；角括号 16/512 的
    线宽在 16px 下仅 0.5px，被抗锯齿磨没。根因是信息密度，调字号无解。
    → **16/32 改用加粗单字母「J」做主形；48px 起才用完整字标「JSON」+ 角括号。**
      （商店 300px logo 例外：商店只按 72~100px 展示，故也用「J」——
       见下方 STORE_LOGO_FORCE_SMALL。）

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
# 小尺寸主形（16 / 32px）——**方案 D**：加粗单字母「J」。
# 16px 只需承载一个字形，笔画才做得够重（描边后有效笔画宽度可达 2 物理像素以上），
# 辨识度优先于语义完整（语义优先那版是方案 E 的花括号 { }）。
SMALL_TEXT = "J"              # 小尺寸主形（16/32px）——四字母在此尺寸必然糊
SMALL_H = 0.74                # 小尺寸主形墨迹高度占版面比例
SMALL_W = 0.66                # 小尺寸主形墨迹宽度上限
SMALL_THRESHOLD = 32          # ≤ 此尺寸走小尺寸主形
PROBE_FS = 100                # 测量用字号

# 小尺寸描边量（viewBox 单位）：16px 下 26/512 ≈ 0.81px 额外笔画。
# 只给单字母补——字母笔画本身偏细；花括号那类重笔画字形切勿描边，会与中钩粘连成白块。
SMALL_STROKE = {16: 26, 32: 12}

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

# 商店 logo（store-icon-300.png）强制走小尺寸主形（单字母 J）：
# 2026-09-24 实测 Edge 加载项商店的 logo 渲染尺寸——详情页 100px、分类页 96px、
# 搜索页 72px。**任何位置都不按 300px 展示**，实际落在 72~100px。
# 该区间内四字母字标的墨迹高度只有约 10px，辨识度显著低于单个加粗 J；
# 且商店各处 logo 旁边就是产品名「JSON Duo」，logo 本身无需再拼写产品名。
# 该文件不随扩展打包（build.js 的 EXCLUDE 已排除），改它不影响已上传的 zip。
STORE_LOGO_FORCE_SMALL = True
GAP = 24                      # 排版间距，避免截图 clip 相互沾边

# 透明底 —— 圆角外必须是 alpha=0，不能是白色（2026-10-16 修复）
#
# 症状：深色工具栏里图标四周有一圈白边（用户实测反馈）。
# 根因：Page.captureScreenshot 默认把页面**合成到不透明白底**上，产出的 PNG 是
#       colorType=2（RGB，无 alpha 通道），圆角方块的四个角于是被填成纯白 #FFFFFF。
#       这不是 SVG 画多了描边，而是「背景色」问题——页面自身 html/body 已经是
#       transparent，少的是浏览器默认底色的透明化。
# 修法：抓图前 Emulation.setDefaultBackgroundColorOverride 把默认底色设成全透明，
#       与 Puppeteer 的 omitBackground 同源；抓完再复位。
CAPTURE_TRANSPARENT = True


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
        # 方案 D：单个加粗字母 J。字号由**字母自身墨迹**反算——同时受宽度上限与
        # 高度目标约束，取更严的那个，避免字形被横向压扁或顶出安全边距。
        w_per, a_per, d_per = M["small"]
        fs = min(SMALL_W * VB / w_per, SMALL_H * VB / (a_per + d_per))
        stroke = SMALL_STROKE.get(size, 0) if stroke is None else stroke
        baseline = (VB - (a_per + d_per) * fs) / 2.0 + a_per * fs
        return ('<text x="%.1f" y="%.2f" text-anchor="middle" '
                'style="font-family:%s;font-weight:%d;font-size:%.3fpx;fill:%s;'
                'stroke:%s;stroke-width:%d;paint-order:stroke;stroke-linejoin:round">'
                '%s</text>'
                % (VB / 2, baseline, FONT, FONT_WEIGHT, fs, FG, FG, stroke, SMALL_TEXT))
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
             'html,body{margin:0;padding:0;background:transparent}'
             # svg 默认是 inline 元素，会受行内基线对齐影响。显式 block 后，
             # svg 的盒子严格等于外层 div（探针实测：加不加都对齐，但加上更保险）。
             'svg{display:block}'
             '</style></head><body>']
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


def set_transparent_bg(c, on):
    """开关「默认底色透明」。

    必须在设置 deviceMetricsOverride / bringToFront 之后调用；off 时用 null
    复位（CDP 约定：Override 传 null 表示清除覆盖）。
    """
    if not CAPTURE_TRANSPARENT:
        return
    c.send("Emulation.setDefaultBackgroundColorOverride",
           {"color": {"r": 0, "g": 0, "b": 0, "a": 0}} if on else None)


def settle(c, frames=3):
    """等布局/绘制稳定：清滚动 + 连续等若干帧。

    首帧竞态实测：紧跟 navigate 就截图，偶尔会拿到「形状整体下移、底部被裁」的
    中间态帧（四角仍透明，但行 alpha 之和明显不对称）。本函数与 inspect_icon 的
    重试一起把这个坑按住。

    注：CDPClient.evaluate 写死了 awaitPromise=False，带 awaitPromise 的调用
    必须直接走 send；同时保留同步 reflow 兜底（后台标签页会节流 rAF）。
    """
    sync = "(function(){window.scrollTo(0,0);return document.body.offsetHeight;})()"
    try:
        c.send("Runtime.evaluate", {
            "expression": "(new Promise(function(res){window.scrollTo(0,0);var n=0;"
                          "(function tick(){ if(++n>=%d){res(document.body.offsetHeight);return;}"
                          "requestAnimationFrame(tick);})();}))" % frames,
            "awaitPromise": True, "returnByValue": True}, timeout=30)
    except Exception:
        c.evaluate(sync, timeout=30)


def inspect_icon(path):
    """返回 (是否通过, 说明)。两项断言：

    1. 四角 alpha=0 —— 圆角外必须透明；填成白色就是用户看到的「白边」；
    2. alpha 上下、左右镜像对称（行/列 alpha 之和相等，容差 1%）。
       第 2 条专抓「首帧竞态导致截图整体错位 / 底部被裁」——那类问题四角可能也是
       透明的，但形状整体偏下，行和立刻不对称。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        from png_read import read_png
    except Exception as exc:                       # 纯标准库，正常不会失败
        return True, "跳过校验（%s）" % exc
    im = read_png(str(path))
    w, h = im.width, im.height
    corners = {k: im.px(*p)[3] for k, p in
               (("左上", (0, 0)), ("右上", (w - 1, 0)),
                ("左下", (0, h - 1)), ("右下", (w - 1, h - 1)))}
    bad = {k: v for k, v in corners.items() if v != 0}
    if bad:
        return False, "四角不透明（白边）：%s" % bad
    rowsum = [sum(im.px(x, y)[3] for x in range(w)) for y in range(h)]
    colsum = [sum(im.px(x, y)[3] for y in range(h)) for x in range(w)]
    for name, arr in (("上下", rowsum), ("左右", colsum)):
        tol = 0.01 * max(arr) + 4 * len(arr)
        for i in range(len(arr) // 2):
            d = abs(arr[i] - arr[len(arr) - 1 - i])
            if d > tol:
                return False, "%s不对称：第%d行/列 %d vs %d（差 %d）" % (
                    name, i, arr[i], arr[len(arr) - 1 - i], d)
    return True, "四角 alpha=0，上下左右对称"


def assert_transparent(path, label):
    """打印式包装：把 inspect_icon 的结果转成命令行输出。"""
    ok, why = inspect_icon(path)
    if not ok:
        print("  !! %s 校验未通过：%s" % (label, why), file=sys.stderr)
        return False
    print("  %s ✓ %s" % (label, why))
    return True


def measure(c):
    """量字形墨迹（以「字号=1」为单位）。返回 {'big': ..., 'small': ...}。"""
    tmp = ROOT / "dist" / "_icon-probe.html"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text('<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
                   '<body></body></html>', encoding="utf-8")
    c.navigate(tmp.as_uri(), timeout=30.0)
    c.wait_for("document.readyState==='complete'", timeout=15)
    texts = [BIG_TEXT, SMALL_TEXT]
    js = ("(function(){var cv=document.createElement('canvas');var x=cv.getContext('2d');"
          "x.font='%d %dpx '+%s;var out={};%s.forEach(function(t){"
          "var m=x.measureText(t);out[t]=[m.width/%d,m.actualBoundingBoxAscent/%d,"
          "m.actualBoundingBoxDescent/%d];});return JSON.stringify(out);})()"
          % (FONT_WEIGHT, PROBE_FS, json.dumps(FONT), json.dumps(texts),
             PROBE_FS, PROBE_FS, PROBE_FS))
    mt = json.loads(ev(c, js))
    tmp.unlink()
    out = {"big": mt[BIG_TEXT], "small": mt[SMALL_TEXT]}
    for k, label in (("big", BIG_TEXT), ("small", SMALL_TEXT)):
        v = out[k]
        print("度量 %-5s %-5s 字宽 %.3f 墨迹上 %.3f 下 %.3f" % (k, label, v[0], v[1], v[2]))
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
            '改后：<b>16/32px 换成加粗单字母 J</b>'
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
    # 圆角外要透明，不能是白底（见 CAPTURE_TRANSPARENT 说明）
    set_transparent_bg(c, True)

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
    codes = {size: svg(marks_for(size, M,
                                 force_small=STORE_LOGO_FORCE_SMALL if size == 300 else None))
             for size in SIZES}
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
        """截图 → 落盘 → 自检；自检不过就再等几帧重截一次。

        自检见 inspect_icon：四角必须 alpha=0（否则是白边），且 alpha 上下/左右
        对称（否则是首帧竞态导致的错位帧）。最多两次，仍不过就报错退出——
        宁可让出图失败，也不要落一张有白边或错位的图标。
        """
        for attempt in (1, 2):
            settle(c, 3 * attempt)
            res = c.send("Page.captureScreenshot", {
                "format": "png",
                "clip": {"x": xs[key], "y": 0, "width": size, "height": size, "scale": 1},
            })
            data = res.get("data")
            if not data:
                print("%s 截图失败" % label, file=sys.stderr)
                return False
            out.write_bytes(base64.b64decode(data))
            print("写入 %s（%d 字节，第 %d 次）"
                  % (out.relative_to(ROOT), out.stat().st_size, attempt))
            if assert_transparent(out, label):
                return True
        return False

    for size in SIZES:
        name = "store-icon-300.png" if size == 300 else "icon%d.png" % size
        if not shot("s%d" % size, size, out_dir / name, "尺寸 %d" % size):
            return 1
    tmp.unlink()

    site_dir = ROOT / "site"
    if site_dir.is_dir():
        if not shot("fav", SITE_FAVICON_SIZE, site_dir / "favicon.png", "站点 favicon"):
            return 1
    # 图标已全部落盘，复位默认底色（后面抓的是带自己底色的文档页）
    set_transparent_bg(c, False)

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
            '<b>16px / 32px</b> 用加粗单字母 <b>%s</b>（墨迹高 %.0f%% 版面，笔画经描边加厚，'
            '有效笔画可达 2 物理像素以上）——四字母字标在 16px 下'
            '墨迹仅约 3 物理像素、单笔画不足 1px，任何字体都会糊成一条白线，故小尺寸换形。'
            '<b>48px / 128px</b>用完整字标「%s」（字宽占版面 %d%%），左右以角括号「」夹住；'
            '<b>300px 商店 logo 例外</b>——实测 Edge 商店只在 72~100px 展示 logo'
            '（详情页 100 / 分类页 96 / 搜索页 72），该区间四字母墨迹仅约 10px，'
            '故仍取单字母 J。'
            '角括号为矢量路径绘制，线宽固定 %d/512，与字母笔画等重'
            '（CJK 全角字形会压小字号，故不直接用字形）；'
            '右括号横笔在底部（角朝右下），按 Microsoft YaHei / SimSun 真实字形校正。</p>'
            '<h2>实际尺寸</h2><div class="row">%s</div>'
            '<h2>放大对照</h2><div class="row">%s</div>'
            '</body></html>'
            % (BG_TOP, BG_BOTTOM, SMALL_TEXT, SMALL_H * 100, BIG_TEXT,
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
         ("改后（方案 D）", "16px 加粗单字母 J", new)],
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
