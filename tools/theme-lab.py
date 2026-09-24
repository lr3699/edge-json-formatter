#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
页面主题色比稿实验室。

做法：**不改任何源文件**，用 CDP 打开真实的 site/index.html 与 site/app.html，
在运行时注入一组 CSS 变量覆盖（候选配色），逐张截图，再合成对照页。
这样看到的是真实版式 + 真实组件（按钮、药丸、卡片、代码块、工作台面板），
而不是手画的 mock——差异只来自配色，归因干净。

语法高亮色（键名/字符串/数字/布尔）**所有候选共用同一套**，
因为语法色不是品牌，共用才能把变量收敛到「品牌主色」这一个维度上。

用法：
    python tools/theme-lab.py --port 9341 --base http://127.0.0.1:8123
"""
import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
from cdp import CDPClient  # noqa: E402

OUT = ROOT / "docs" / "theme-redesign"

# ---------------------------------------------------------------- 语法色 --
# 所有候选共用。相对现状的三处改动：
#   键名  #92278f 品红 -> #7C3AED 紫罗兰（品红在 JSON 里少见，和任何强调色都冲突）
#   数字  #20a8e0 浅蓝 -> #B45309 琥珀（浅蓝与「蓝色系主色」必然撞车）
#   字符串 #3ab54a -> #15803D（加深，白底对比度从 2.66:1 提到 5.01:1）
# 现状的致命处：--str 与 --primary **完全同值 #3ab54a**，字符串和品牌按钮一个颜色。
SYNTAX_LIGHT = {
    "--key": "#7C3AED",
    "--key-soft": "rgba(124, 58, 237, .08)",
    "--str": "#15803D",
    "--num": "#B45309",
    "--bool": "#B91C1C",
}
SYNTAX_DARK = {
    "--key": "#C4B5FD",
    "--key-soft": "rgba(196, 181, 253, .14)",
    "--str": "#7EE787",
    "--num": "#F0B429",
    "--bool": "#FF9492",
}

# ---------------------------------------------------------------- 候选配色 --
# keys: style.css（落地页）+ editor.css（工作台）+ app.css（顶部导航药丸）
PALETTES = [
    {
        "id": "cur",
        "name": "0 · 现状（对照）",
        "note": "绿 #3ab54a。与字符串语法色**完全同值**，且与数字浅蓝、键名品红三色并存；"
                "白底对比度 2.66:1，未达 AA。",
        "site": {}, "site_dark": {}, "editor": {}, "editor_dark": {},
        "topnav": {}, "swatch": ["#3ab54a", "#20a8e0", "#92278f", "#e85050", "#ffffff"],
    },
    {
        "id": "blue",
        "name": "A · 电光蓝",
        "note": "主色 #2563EB，与图标「黑白编辑器」气质同源，与四色语法高亮**全部错开**。"
                "白底 5.17:1 达标；开发者工具的心智色（DevTools / VS Code）。",
        "site": {
            "--primary": "#2563EB", "--primary-hover": "#1D4ED8",
            "--accent-soft": "#EFF6FF",
        },
        "site_dark": {
            "--primary": "#3B82F6", "--primary-hover": "#60A5FA",
            "--accent-soft": "#0F2547",
        },
        "editor": {
            "--brand": "#2563EB", "--brand-2": "#1D4ED8",
            "--accent": "#2563EB", "--ring": "rgba(37, 99, 235, .28)",
            "--ok": "#15803D",
        },
        "editor_dark": {
            "--brand": "#60A5FA", "--brand-2": "#3B82F6",
            "--accent": "#60A5FA", "--ring": "rgba(96, 165, 250, .3)",
            "--ok": "#7EE787",
        },
        "topnav": {"--topnav-active": "rgba(37, 99, 235, .12)"},
        "topnav_dark": {"--topnav-active": "rgba(96, 165, 250, .18)"},
        "swatch": ["#2563EB", "#1D4ED8", "#7C3AED", "#15803D", "#B45309"],
    },
    {
        "id": "teal",
        "name": "B · 深青",
        "note": "主色 #0F766E。品牌从绿到青的**连续过渡**，改动最小、观感最稳；"
                "但青与字符串绿同属绿系（色相差约 33°），分离度弱于 A。白底 5.47:1 达标。",
        "site": {
            "--primary": "#0F766E", "--primary-hover": "#115E59",
            "--accent-soft": "#ECFDF5",
        },
        "site_dark": {
            "--primary": "#14B8A6", "--primary-hover": "#2DD4BF",
            "--accent-soft": "#0B3B36",
        },
        "editor": {
            "--brand": "#0F766E", "--brand-2": "#0D9488",
            "--accent": "#0E7490", "--ring": "rgba(15, 118, 110, .28)",
            "--ok": "#15803D",
        },
        "editor_dark": {
            "--brand": "#2DD4BF", "--brand-2": "#14B8A6",
            "--accent": "#38BDF8", "--ring": "rgba(45, 212, 191, .3)",
            "--ok": "#7EE787",
        },
        "topnav": {"--topnav-active": "rgba(15, 118, 110, .12)"},
        "topnav_dark": {"--topnav-active": "rgba(45, 212, 191, .18)"},
        "swatch": ["#0F766E", "#115E59", "#0E7490", "#15803D", "#B45309"],
    },
    {
        "id": "ink",
        "name": "C · 石墨黑 + 蓝焦点",
        "note": "主 CTA 用近黑 #0F172A，**与图标底板同色**，品牌识别最直接；"
                "焦点/链接另用蓝 #2563EB。最克制、最像编辑器，但按钮的「可点击感」弱于 A。",
        "site": {
            "--primary": "#0F172A", "--primary-hover": "#1E293B",
            "--accent-soft": "#F1F5F9",
        },
        "site_dark": {
            "--primary": "#E2E8F0", "--primary-hover": "#CBD5E1",
            "--accent-soft": "#1E293B",
        },
        "editor": {
            "--brand": "#0F172A", "--brand-2": "#334155",
            "--accent": "#2563EB", "--ring": "rgba(37, 99, 235, .28)",
            "--ok": "#15803D",
        },
        "editor_dark": {
            "--brand": "#E2E8F0", "--brand-2": "#CBD5E1",
            "--accent": "#60A5FA", "--ring": "rgba(96, 165, 250, .3)",
            "--ok": "#7EE787",
        },
        "topnav": {"--topnav-active": "rgba(15, 23, 42, .10)"},
        "topnav_dark": {"--topnav-active": "rgba(226, 232, 240, .16)"},
        "swatch": ["#0F172A", "#1E293B", "#2563EB", "#7C3AED", "#15803D"],
    },
]

# 现状（对照组）不动语法色：它本身就是被诊断的对象
for p in PALETTES:
    if p["id"] == "cur":
        continue
    p["site"].update(SYNTAX_LIGHT)
    p["site_dark"].update(SYNTAX_DARK)

PAGES = [("index", "index.html", 1900), ("app", "app.html", 900)]

# 只有 app.html（工作台）有 data-theme 手动切换（editor.css 支持）；
# 落地页 style.css 仅 @media(prefers-color-scheme)，注入覆盖也变不出深色。
# 所以深色只对工作台取样——否则会拿「深色主色 + 浅色底」的假象去误导对照。
DARK_PAGES = {"app"}


def override_css(p, dark=False):
    """生成覆盖用的 <style> 内容。"""
    site = dict(p["site"])
    editor = dict(p["editor"])
    topnav = dict(p.get("topnav", {}))
    if dark:
        site = dict(p["site_dark"])
        editor = dict(p["editor_dark"])
        topnav = dict(p.get("topnav_dark", {}))
        if p["id"] != "cur":
            site.update(SYNTAX_DARK)
    # 站点把「链接色」直接绑在语法 token --num 上（a{color:var(--num)}），
    # 主色改变后链接必须跟着走，否则蓝主色配琥珀链接。
    # 注意必须是**独立规则**，不能拼进 decl 再包 :root{}——那样会被解析成
    # :root 内的非法声明，整条规则失效（踩过：主按钮文字色被吃掉、白底白字）。
    decl = "".join("%s:%s;" % (k, v) for k, v in site.items())
    edecl = "".join("%s:%s;" % (k, v) for k, v in editor.items())
    tdecl = "".join("%s:%s;" % (k, v) for k, v in topnav.items())
    link = ("a:not(.btn-solid):not(.nav-cta){color:var(--primary);}"
            # 现状缺陷：顶栏 CTA 药丸吃的是 .top nav a 的 --muted 灰（#9aa0a6），
            # 落在绿底上只有 1.01:1，文字等于隐形。这处**对所有候选（含现状）**
            # 都补上白字，否则药丸是无字色块，颜色对比根本无从判起。
            "nav a.nav-cta{color:#fff;}")
    blocks = [":root{%s}" % decl, ":root{%s}" % edecl, link]
    if tdecl:
        blocks.append(":root{%s}" % tdecl)
    if dark:
        # 覆盖 data-theme="dark"（工作台主题按钮）与系统深色两条路径
        blocks.append('html[data-theme="dark"]{%s}' % (edecl + tdecl))
        blocks.append("@media (prefers-color-scheme:dark){"
                      "html[data-theme=dark],:root{%s}}" % (decl + edecl + tdecl))
    else:
        blocks.append('html[data-theme="light"]{%s}' % (edecl + tdecl))
    return "\n".join(blocks)


def inject(c, css):
    c.evaluate(
        "(function(){var el=document.getElementById('theme-lab');"
        "if(!el){el=document.createElement('style');el.id='theme-lab';"
        "document.head.appendChild(el);}el.textContent=%s;return 1;})()"
        % json.dumps(css), timeout=30)


def shot(c, width, height, out):
    """截图当前页（**不导航** —— 导航会把注入的覆盖样式冲掉）。"""
    res = c.send("Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": True, "fromSurface": True,
        "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}})
    out.write_bytes(base64.b64decode(res["data"]))
    return out.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9341)
    ap.add_argument("--base", default="http://127.0.0.1:8123")
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=300.0)
    if not c.is_alive():
        print("CDP %d 无响应" % args.port, file=sys.stderr)
        return 1
    c.ensure_page()
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    OUT.mkdir(parents=True, exist_ok=True)

    files = {}
    for p in PALETTES:
        for page, path, height in PAGES:
            modes = [("light", False)]
            if page in DARK_PAGES:
                modes.append(("dark", True))
            for label, dark in modes:
                c.navigate("%s/%s" % (args.base, path), timeout=60.0)
                c.wait_for("document.readyState==='complete'", timeout=30)
                inject(c, override_css(p, dark))
                if dark:
                    c.evaluate("document.documentElement.setAttribute('data-theme','dark')", timeout=10)
                c.evaluate("new Promise(function(r){return requestAnimationFrame(function(){"
                           "requestAnimationFrame(r);});})", timeout=15)
                c.evaluate("window.scrollTo(0,0)", timeout=10)
                name = "%s-%s-%s.png" % (p["id"], page, label)
                files[(p["id"], page, label)] = name
                n = shot(c, 1280, height, OUT / name)
                print("写入 %-28s %6d B" % (name, n))
                # 另外裁一张首屏顶部：决策图用它，色都在这里
                if not dark:
                    top = "%s-%s-top.png" % (p["id"], page)
                    res = c.send("Page.captureScreenshot", {
                        "format": "png", "captureBeyondViewport": True, "fromSurface": True,
                        "clip": {"x": 0, "y": 0, "width": 1280, "height": 700, "scale": 1}})
                    (OUT / top).write_bytes(base64.b64decode(res["data"]))
                    files[(p["id"], page, "top")] = top

    # ------------------------------------------------------------ 对照页 --
    rows = []
    for p in PALETTES:
        sw = "".join('<i style="background:%s"></i>' % s for s in p["swatch"])
        cells = []
        for page, _path, _h in PAGES:
            for mode, cap in (("light", ""), ("dark", "（深色）")):
                if (p["id"], page, mode) not in files:
                    continue
                cells.append(
                    '<figure class="shot"><img src="%s" alt="">'
                    '<figcaption>%s</figcaption></figure>'
                    % (files[(p["id"], page, mode)],
                       {"index": "落地页", "app": "工作台"}[page] + cap))
        rows.append(
            '<section class="cand" id="%s"><header><h3>%s</h3><div class="sw">%s</div></header>'
            '<p class="note">%s</p><div class="shots">%s</div></section>'
            % (p["id"], p["name"], sw, p["note"], "".join(cells)))

    page = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>JSON Duo 主题色比稿</title><style>'
            'body{background:#0f1115;color:#e7eaf0;margin:0;padding:34px 40px 70px;'
            'font-family:"Segoe UI","Microsoft YaHei UI","Microsoft YaHei",sans-serif}'
            'h1{font-size:21px;font-weight:650;margin:0 0 10px}'
            'p.lede{color:#9aa3b2;font-size:13px;line-height:1.85;max-width:1080px;margin:0 0 8px}'
            'p.lede b{color:#e7eaf0}'
            'p.lede code{background:#1c1f27;padding:1px 6px;border-radius:5px;font-size:12px}'
            '.cand{background:#15181e;border:1px solid #232832;border-radius:14px;'
            'padding:20px 22px;margin:0 0 18px}'
            '.cand header{display:flex;align-items:center;gap:14px;margin:0 0 8px}'
            'h3{font-size:15px;font-weight:650;margin:0;color:#f3f5f8}'
            '.sw{display:flex;gap:6px}'
            '.sw i{width:20px;height:20px;border-radius:6px;display:block;'
            'box-shadow:inset 0 0 0 1px rgba(255,255,255,.14)}'
            '.note{color:#9aa3b2;font-size:12px;line-height:1.8;margin:0 0 14px;max-width:1080px}'
            '.note b{color:#e7eaf0}'
            '.shots{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap}'
            'figure.shot{margin:0}'
            'figure.shot img{display:block;border-radius:8px;border:1px solid #2a2f3a;'
            'background:#fff}'
            'figcaption{margin-top:7px;font-size:11px;color:#7f8899}'
            '.scroll{max-height:520px;overflow:hidden}'
            '</style></head><body>'
            '<h1>JSON Duo 主题色比稿</h1>'
            '<p class="lede">下面全部是<b>真实页面</b>的渲染截图（不是手绘 mock）：'
            'CDP 打开 site/index.html 与 site/app.html，运行时注入候选配色变量后原样截屏，'
            '所以按钮、药丸、卡片、代码块、工作台面板都是真的。'
            '<b>四个候选共用同一套语法高亮色</b>（紫键名 / 深绿字符串 / 琥珀数字 / 砖红布尔），'
            '唯一变量是品牌主色——差异可干净归因。</p>'
            '<p class="lede">看三处即可判断：<b>①</b> 顶栏「在线试用」药丸与主按钮；'
            '<b>②</b> 代码块里字符串的绿会不会和主色混淆；'
            '<b>③</b> 工作台顶栏品牌区与焦点蓝是否还有两套强调色打架。</p>'
            '%s</body></html>' % "".join(rows))
    (OUT / "lab.html").write_text(page, encoding="utf-8")

    # -------------------------------------------------- 决策图（一屏可判）--
    qrows = []
    for p in PALETTES:
        sw = "".join('<i style="background:%s"></i>' % s for s in p["swatch"])
        pid = p["id"]
        imgs = []
        for key, cap in (((pid, "index", "top"), "落地页首屏"),
                         ((pid, "app", "light"), "工作台 · 浅色"),
                         ((pid, "app", "dark"), "工作台 · 深色")):
            if key not in files:
                print("警告：决策图缺 %s，跳过" % (key,), file=sys.stderr)
                continue
            imgs.append('<figure><img src="%s" alt=""><figcaption>%s</figcaption></figure>'
                        % (files[key], cap))
        qrows.append('<div class="qrow"><div class="qhead"><h3>%s</h3><div class="sw">%s</div>'
                     '<p>%s</p></div><div class="imgs">%s</div></div>'
                     % (p["name"], sw, p["note"], "".join(imgs)))
    quick = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
             '<title>主题色决策图</title><style>'
             'body{background:#0f1115;color:#e7eaf0;margin:0;padding:24px 26px 40px;'
             'font-family:"Segoe UI","Microsoft YaHei UI","Microsoft YaHei",sans-serif}'
             'h1{font-size:18px;font-weight:650;margin:0 0 8px}'
             'p.lede{color:#9aa3b2;font-size:12px;line-height:1.8;max-width:1060px;margin:0 0 20px}'
             'p.lede b{color:#e7eaf0}'
             '.qrow{display:flex;gap:18px;align-items:flex-start;background:#15181e;'
             'border:1px solid #232832;border-radius:12px;padding:16px 18px;margin-bottom:14px}'
             '.qhead{width:250px;flex:0 0 250px}'
             '.qhead h3{font-size:14px;font-weight:650;margin:0 0 8px;color:#f3f5f8}'
             '.qhead p{color:#9aa3b2;font-size:11px;line-height:1.7;margin:9px 0 0}'
             '.qhead p b{color:#e7eaf0}'
             '.sw{display:flex;gap:5px}'
             '.sw i{width:17px;height:17px;border-radius:5px;display:block;'
             'box-shadow:inset 0 0 0 1px rgba(255,255,255,.14)}'
             '.imgs{display:flex;gap:14px}'
             'figure{margin:0}figure img{display:block;width:262px;border-radius:7px;'
             'border:1px solid #2a2f3a;background:#fff}'
             'figcaption{margin-top:6px;font-size:10px;color:#7f8899}'
             '</style></head><body>'
             '<h1>主题色决策图 · 真实页面渲染</h1>'
             '<p class="lede">三列分别是：落地页首屏（浅色）、工作台（浅色）、工作台（深色）。'
             '全部是 site/index.html 与 site/app.html 的<b>真实渲染</b>，'
             '运行时注入候选变量后原样截屏，缩放到 20%%。'
             '判断标准两条：<b>①</b> 主色和四色语法高亮能不能一眼分开；'
             '<b>②</b> 工作台里还会不会同时出现两套强调色（品牌绿 + 焦点蓝）。</p>'
             '%s</body></html>' % "".join(qrows))
    (OUT / "quick.html").write_text(quick, encoding="utf-8")

    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1240, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    for html, png in (("quick.html", "quick.png"), ("lab.html", "lab.png")):
        c.navigate((OUT / html).as_uri(), timeout=60.0)
        c.wait_for("document.readyState==='complete'", timeout=30)
        c.wait_for("document.fonts.status==='loaded'", timeout=20)
        h = c.evaluate("Math.ceil(document.body.scrollHeight)", timeout=30)
        if isinstance(h, dict):
            h = h.get("value", h)
        res = c.send("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True, "fromSurface": True,
            "clip": {"x": 0, "y": 0, "width": 1240, "height": int(h), "scale": 1}})
        (OUT / png).write_bytes(base64.b64decode(res["data"]))
        print("对照页 docs/theme-redesign/%s（页高 %d）" % (html, int(h)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
