#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-theme.py —— 验收「深浅主题在全页与右侧树视图之间始终一致」。

背景（这脚本就是为它写的回归护栏）：
  系统深色主题下，整页变深、**右侧 JSON 树视图却仍是白底**。
  根因不在 CSS，在 viewer.js 的初始化顺序：applyTheme() 靠 `var mql`（系统深色
  媒体查询）把 opts.theme === 'auto' 折算成 light / dark，而 createViewer 最前面
  就调用了 applyTheme()，那时 mql 还只是声明提升出来的 undefined → 'auto' 恒被折算
  成 light → 树视图拿到 data-theme="light"。整页看着还是深的（editor.css 的深色
  块挂在 @media 里、选择器是 :not([data-theme="light"])，没有属性照样命中），
  于是只有右栏不跟。系统主题**中途**变化时反而正常（那时 mql 已赋值）——这个
  「刷新就白、切一下就好」的不对称，正是这处顺序 bug 的指纹。

判据：<html data-theme>、.jf-root[data-theme] 与两者的**计算背景色**必须同深浅。

用法：
    python tools/verify-theme.py --port 9371 --base http://127.0.0.1:8123 [--shots]

前置：
  · Edge 已用 --remote-debugging-port=<port> 启动（建议 --headless=new）
  · 本地静态服务已跑着：node tools/serve.js 8123
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
from cdp import CDPClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "shots" / "theme"

PAGES = [
    ("网页版工作台", "site/app.html"),
    ("扩展独立编辑页", "src/editor/editor.html"),
]

SAMPLE = json.dumps({
    "code": "0",
    "msg": "success",
    "data": {
        "orderId": "600653836507516928",
        "amount": 128.5,
        "paid": True,
        "refunded": None,
        "tags": ["vip", "2026-09"],
        "buyer": {"id": 10086, "nickname": "张三"},
    },
    "ts": 1784173433013,
}, ensure_ascii=False, indent=2)

HELPERS = r"""
window.__th = {
  setInput: function (text) {
    var ta = document.getElementById('input');
    if (!ta) return 'NO_INPUT';
    ta.hidden = false;
    ta.value = text;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return 'OK';
  },
  clearStore: function () {
    try { localStorage.clear(); } catch (e) { /* file:// 下可能不可写 */ }
    return 'OK';
  },
  /** 树视图的配色状态：属性 + 真实计算样式（属性对不对，最终看这里） */
  state: function () {
    var root = document.querySelector('#viewer .jf-root') || document.querySelector('.jf-root');
    var cs = root ? getComputedStyle(root) : null;
    return JSON.stringify({
      media: (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
        ? 'dark' : 'light',
      htmlAttr: document.documentElement.getAttribute('data-theme'),
      viewerAttr: document.getElementById('viewer')
        ? document.getElementById('viewer').getAttribute('data-theme') : null,
      rootAttr: root ? root.getAttribute('data-theme') : 'NO_ROOT',
      bodyBg: getComputedStyle(document.body).backgroundColor,
      rootBg: cs ? cs.backgroundColor : null,
      rootColor: cs ? cs.color : null,
      themeLabel: window.__th.themeLabel(),
      rows: document.querySelectorAll('.jf-row').length
    });
  },
  /** 主题按钮上的当前档位文案（跟随系统 / 浅色 / 深色）。
   *  2026-10-19 起主题入口统一为顶栏右上角那枚三档循环钮（跟随系统 →
   *  浅色 → 深色），右侧树工具条 / 大文档工具条的循环钮已下线，
   *  所以选择器优先找 #btnThemeAuto。 */
  themeLabel: function () {
    var b = document.getElementById('btnThemeAuto');
    if (b) return (b.textContent || '').trim() || null;
    var bs = document.querySelectorAll('#viewer .jf-btn, .jf-btn');
    for (var i = 0; i < bs.length; i++) {
      var t = (bs[i].textContent || '').trim();
      if (t === '跟随系统' || t === '浅色' || t === '深色') return t;
    }
    return null;
  },
  /** 点主题按钮，直到档位文案等于 target（最多 3 次，正好一圈） */
  cycleThemeTo: function (target) {
    var b = document.getElementById('btnThemeAuto');
    if (b) {
      for (var k = 0; k < 4; k++) {
        if ((b.textContent || '').trim() === target) return target + '/OK';
        b.click();
      }
      return (b.textContent || '').trim() + '/FAIL';
    }
    var bs = document.querySelectorAll('#viewer .jf-btn, .jf-btn');
    for (var i = 0; i < bs.length; i++) {
      var t = (bs[i].textContent || '').trim();
      if (t !== '跟随系统' && t !== '浅色' && t !== '深色') continue;
      for (var k = 0; k < 4; k++) {
        if ((bs[i].textContent || '').trim() === target) return target + '/OK';
        bs[i].click();
      }
      return (bs[i].textContent || '').trim() + '/MISS';
    }
    return 'NO_THEME_BTN';
  }
};
true;
"""

PASS, FAIL = [], []

# 扩展独立编辑页直接开在普通 HTTP 下时没有 chrome.storage，设置存不下来，
# 「刷新后手动档位仍生效」这条就只能空跑。给它挂一个 localStorage 版的
# chrome.storage 垫片（只在测试里注入，源文件不动）——垫片同时让 editor.js 的
# HAS_EXT 判定为真，与真实扩展环境一致。
CHROME_SHIM = r"""
(function () {
  var KEY = '__chromeStorageShim';
  function read() {
    try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { return {}; }
  }
  function write(patch) {
    try { localStorage.setItem(KEY, JSON.stringify(Object.assign(read(), patch))); } catch (e) {}
  }
  function area() {
    return {
      get: function (defs, cb) { cb(Object.assign({}, defs, read())); },
      set: function (patch, cb) { write(patch); if (cb) cb(); }
    };
  }
  window.chrome = window.chrome || {};
  if (!chrome.runtime) {
    chrome.runtime = { id: 'test-shim', lastError: null, getURL: function (p) { return p; } };
  }
  if (!chrome.storage) {
    chrome.storage = {
      sync: area(), local: area(),
      onChanged: { addListener: function () {}, removeListener: function () {} }
    };
  }
})();
"""


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  " + str(detail)) if detail else ""))


def luminance(rgb):
    """'rgb(r, g, b)' → 相对亮度均值。只用来把「深/浅」二值化，不需要色彩学精度。"""
    try:
        nums = [int(x) for x in rgb.strip().lower().replace("rgba(", "").replace("rgb(", "")
                .replace(")", "").split(",")[:3]]
    except Exception:
        return None
    return sum(nums) / 3.0


def is_dark(rgb):
    lum = luminance(rgb)
    return None if lum is None else lum < 96


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9371)
    ap.add_argument("--base", default="http://127.0.0.1:8123")
    ap.add_argument("--shots", action="store_true", help="把关键状态截图到 docs/shots/theme/")
    args = ap.parse_args()

    c = CDPClient(host="127.0.0.1", port=args.port, timeout=180.0)
    if not c.is_alive():
        print("CDP 端口 %d 不通：请先启动 Edge（--remote-debugging-port=%d）" % (args.port, args.port))
        return 2
    c.ensure_page()
    c.send("Emulation.setDeviceMetricsOverride",
           {"width": 1360, "height": 860, "deviceScaleFactor": 1, "mobile": False})
    if args.shots:
        OUT.mkdir(parents=True, exist_ok=True)

    script_id = None

    def ev(expr, timeout=30):
        r = c.evaluate(expr, timeout=timeout)
        return r.get("value", r) if isinstance(r, dict) else r

    def set_media(scheme):
        c.send("Emulation.setEmulatedMedia",
               {"media": "", "features": [{"name": "prefers-color-scheme", "value": scheme}]})

    def shot(name):
        if not args.shots:
            return
        res = c.send("Page.captureScreenshot", {
            "format": "png", "fromSurface": True,
            "clip": {"x": 0, "y": 0, "width": 1360, "height": 860, "scale": 1}})
        p = OUT / name
        p.write_bytes(base64.b64decode(res["data"]))
        print("        截图 → %s" % p.relative_to(ROOT))

    def open_page(path, scheme, first=False):
        """干净地打开一个页面：清掉持久化设置 → 设系统主题 → 加载 → 粘内容。"""
        set_media(scheme)
        c.navigate("%s/%s" % (args.base, path), timeout=60.0)
        c.wait_for("document.readyState==='complete'", timeout=30)
        if first:
            ev("(function(){try{localStorage.clear()}catch(e){};return 'OK';})()")
            c.navigate("%s/%s" % (args.base, path), timeout=60.0)
            c.wait_for("document.readyState==='complete'", timeout=30)
        ev(HELPERS)
        ev("window.__th.setInput(%s)" % json.dumps(SAMPLE))
        for _ in range(40):
            if json.loads(ev("window.__th.state()"))["rows"] > 0:
                break
            time.sleep(0.2)
        time.sleep(0.25)
        return json.loads(ev("window.__th.state()"))

    def assert_both(label, st, expect, extra=""):
        """expect: 'dark' | 'light'；三层判据必须同时成立。"""
        html_attr_dark = st["htmlAttr"] == "dark"
        root_attr_dark = st["rootAttr"] == "dark"
        body_dark = is_dark(st["bodyBg"])
        root_dark = is_dark(st["rootBg"])
        want_dark = expect == "dark"
        detail = ("html=%s/%s 树=%s/%s 背景=%s" % (
            st["htmlAttr"], st["bodyBg"], st["rootAttr"], st["rootBg"], st["themeLabel"]))
        ok = (html_attr_dark == want_dark and root_attr_dark == want_dark
              and body_dark == want_dark and root_dark == want_dark)
        # 一致性判据：两者同深浅（哪怕期望值本身判错，这条也要单独报出来）
        check("%s —— 三层主题一致（期望 %s）%s" % (label, expect, extra), ok, detail)
        if html_attr_dark != root_attr_dark or body_dark != root_dark:
            check("  ↑ 整页与树视图同深浅", False,
                  "整页 %s / 树视图 %s ← 不一致" % ("深" if body_dark else "浅",
                                                "深" if root_dark else "浅"))
        return ok

    for page_name, page_path in PAGES:
        print("\n================ %s（%s） ================" % (page_name, page_path))

        # 扩展页需要 chrome.storage 垫片；网页版自带 web-storage.js，不用垫
        if page_path.startswith("src/"):
            if script_id is None:
                script_id = c.send("Page.addScriptToEvaluateOnNewDocument",
                                   {"source": CHROME_SHIM}).get("identifier")
                print("        已注入 chrome.storage 垫片（%s）" % script_id)
        elif script_id is not None:
            c.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": script_id})
            script_id = None

        # A. 加载时系统就是深色 —— 本次修复的正题
        st = open_page(page_path, "dark", first=True)
        assert_both("A 加载即系统深色", st, "dark")
        shot("%s-A-load-dark.png" % page_path.replace("/", "_"))

        # B / C. 开着页面把系统主题来回切（修复前这条路是好的，一并守住）
        set_media("light")
        time.sleep(0.5)
        assert_both("B 系统中途切浅色", json.loads(ev("window.__th.state()")), "light")
        set_media("dark")
        time.sleep(0.5)
        assert_both("C 系统中途切回深色", json.loads(ev("window.__th.state()")), "dark")

        # D. 系统浅色 + 手动选深色（手动档必须压过系统）
        open_page(page_path, "light")
        print("        点击主题按钮 → %s" % ev("window.__th.cycleThemeTo('深色')"))
        assert_both("D 系统浅色 + 手动深色", json.loads(ev("window.__th.state()")), "dark")
        shot("%s-D-manual-dark.png" % page_path.replace("/", "_"))

        # E. 刷新后手动档位仍生效（持久化 + 首帧就要对，不能等用户再切一次）
        set_media("light")
        c.navigate("%s/%s" % (args.base, page_path), timeout=60.0)
        c.wait_for("document.readyState==='complete'", timeout=30)
        ev(HELPERS)
        ev("window.__th.setInput(%s)" % json.dumps(SAMPLE))
        for _ in range(40):
            if json.loads(ev("window.__th.state()"))["rows"] > 0:
                break
            time.sleep(0.2)
        assert_both("E 刷新后持久化的手动深色", json.loads(ev("window.__th.state()")), "dark")

        # F. 系统深色 + 手动选浅色
        open_page(page_path, "dark")
        print("        点击主题按钮 → %s" % ev("window.__th.cycleThemeTo('浅色')"))
        assert_both("F 系统深色 + 手动浅色", json.loads(ev("window.__th.state()")), "light")

        # 收尾：档位回「跟随系统」，清掉这次跑出来的持久化设置
        ev("window.__th.cycleThemeTo('跟随系统')")
        st = open_page(page_path, "dark")
        assert_both("G 收尾：档位回跟随系统 + 系统深色", st, "dark")

    print("\n------------ 汇总 ------------")
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    for n in FAIL:
        print("  FAIL: " + n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
