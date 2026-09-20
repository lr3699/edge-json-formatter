#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shoot.py —— 批量重拍扩展截图（v1.1.3：工具栏精简 + 全展开 + 压缩真生效 + 全局深色）。

自包含：自己启动带扩展的 Edge（CDP 调试模式），自己起假接口服务，
按脚本顺序截图到 docs/shots/ 与 docs/，最后打印结果清单。

用法：
    python tools/shoot.py [--port 9335] [--keep]   # --keep 不退出浏览器
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = Path(
    os.environ.get("CDP_SKILL_SCRIPTS",
                   Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"))
sys.path.insert(0, str(SKILL_SCRIPTS))
from cdp import CDPClient, CDPError  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
UNPACKED = ROOT / "dist" / "unpacked"
SERVER_PORT = 18543

ERROR_HOOK = """
window.__errs = [];
window.addEventListener('error', function (e) { window.__errs.push('error: ' + (e.message || e.type)); });
window.addEventListener('unhandledrejection', function (e) { window.__errs.push('rejection: ' + String(e.reason || '')); });
"""

# 穿透 Shadow DOM 拿到查看器根节点与工具栏按钮。
# content.js 把 viewer 挂在 #__jf_page_host__ 的 shadowRoot 里，
# 主世界 document.querySelector('.jf-root') 查不到，必须走 host.shadowRoot。
JF_HELPERS = """
window.__jfRoot = function () {
  var host = document.getElementById('__jf_page_host__');
  if (host && host.shadowRoot) return host.shadowRoot.querySelector('.jf-root');
  return document.querySelector('.jf-root');  // 编辑页：viewer 直接挂主世界
};
window.__jfButtons = function () {
  var root = window.__jfRoot();
  return root ? root.querySelectorAll('.jf-toolbar button') : [];
};
window.__jfClick = function (match) {
  var btns = window.__jfButtons();
  for (var i = 0; i < btns.length; i++) {
    var t = btns[i].title || '', txt = btns[i].textContent || '';
    if (match === 'theme' && t.indexOf('主题') >= 0) { btns[i].click(); return 'theme'; }
    if (match === 'escape' && txt.indexOf('保留转义') >= 0) { btns[i].click(); return 'escape'; }
    if (match === 'mode' && (txt === '压缩' || txt === '美化')) { btns[i].click(); return 'mode'; }
  }
  return 'NOT_FOUND:' + match;
};
"""


def _reconfigure():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def ev(client, expr, timeout=60.0):
    res = client.send("Runtime.evaluate", {
        "expression": expr, "returnByValue": True, "awaitPromise": True, "userGesture": True,
    }, timeout=timeout)
    if res.get("exceptionDetails"):
        exc = res["exceptionDetails"]
        desc = (exc.get("exception") or {}).get("description") or exc.get("text")
        raise RuntimeError("页面 JS 异常：%s" % desc[:2000])
    return res.get("result", {}).get("value")


def find_extension_id(client):
    for t in client.targets():
        u = t.get("url") or ""
        if u.startswith("chrome-extension://") and u.endswith("/src/background/service-worker.js"):
            return u.split("/")[2]
    return None


def start_edge(port):
    """以 CDP 模式启动带扩展的 Edge（临时 profile）。"""
    from cdp import temp_profile_dir
    profile = temp_profile_dir()
    cmd = [
        EDGE,
        "--remote-debugging-port=%d" % port,
        "--remote-allow-origins=*",
        "--user-data-dir=%s" % profile,
        "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-sync", "--disable-default-apps",
        "--disable-popup-blocking",
        "--load-extension=%s" % str(UNPACKED),
        "--enable-unsafe-extension-debugging",
        "about:blank",
    ]
    creation = 0
    if sys.platform.startswith("win"):
        creation = (getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, creationflags=creation, close_fds=True)

    client = CDPClient(host="127.0.0.1", port=port, timeout=5)
    deadline = time.time() + 30
    while time.time() < deadline:
        if client.is_alive():
            return client.version()
        time.sleep(0.5)
    return None


def main():
    _reconfigure()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9335)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    port = args.port

    shots_dir = ROOT / "docs" / "shots"
    docs_dir = ROOT / "docs"
    shots_dir.mkdir(parents=True, exist_ok=True)

    results = []

    def log(s=""):
        print(s)

    # 1) 启动带扩展的 Edge
    log("启动带扩展的 Edge（端口 %d）..." % port)
    info = start_edge(port)
    if not info:
        log("[失败] Edge 未在 30s 内就绪")
        return 1
    log("Edge 就绪：%s" % info.get("Browser"))

    client = CDPClient(host="127.0.0.1", port=port, timeout=30.0)
    ext_id = None
    deadline = time.time() + 20
    while time.time() < deadline:
        ext_id = find_extension_id(client)
        if ext_id:
            break
        time.sleep(0.5)
    if not ext_id:
        log("[失败] 找不到扩展 service worker")
        return 3
    log("扩展 ID: %s" % ext_id)

    client.ensure_page()
    client.send("Page.enable")
    client.send("Runtime.enable")
    client.send("Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_HOOK})
    client.send("Emulation.setDeviceMetricsOverride",
                {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})

    # 主题状态查询：读工具栏主题按钮的文案（跟随系统/浅色/深色）
    JS_THEME_LABEL = "(function(){var b=window.__jfButtons();for(var i=0;i<b.length;i++){if((b[i].title||'').indexOf('主题')>=0)return b[i].textContent; }return null;})()"
    # 输出模式查询：压缩/美化按钮文案
    JS_MODE_LABEL = "(function(){var b=window.__jfButtons();for(var i=0;i<b.length;i++){var t=b[i].textContent;if(t==='压缩'||t==='美化')return t;}return null;})()"

    def click_theme_until(target_label, max_clicks=3):
        """循环点击主题按钮直到文案变为目标（跟随系统/浅色/深色）。"""
        for _ in range(max_clicks):
            cur = ev(client, JS_THEME_LABEL)
            if cur == target_label:
                return True
            ev(client, "window.__jfClick('theme')")
            time.sleep(0.35)
        return ev(client, JS_THEME_LABEL) == target_label

    def click_mode_until(target_label, max_clicks=2):
        for _ in range(max_clicks):
            cur = ev(client, JS_MODE_LABEL)
            if cur == target_label:
                return True
            ev(client, "window.__jfClick('mode')")
            time.sleep(0.4)
        return ev(client, JS_MODE_LABEL) == target_label

    try:
        # ---------- A) 接管视图：浅色 ----------
        log("\n=== A) 接管 /api/order（浅色）===")
        client.navigate("http://127.0.0.1:%d/api/order" % SERVER_PORT, timeout=30.0)
        client.wait_for("document.readyState === 'complete'", timeout=15.0)
        time.sleep(1.2)
        ev(client, JF_HELPERS)  # 注入 shadow DOM 穿透辅助
        taken = ev(client, "!!window.__jfRoot()")
        # 等渲染完成（默认全展开 + 分批渲染）
        client.wait_for("window.__jfRoot && !!window.__jfRoot() && window.__jfRoot().querySelectorAll('.jf-row').length > 5",
                        timeout=15.0)
        log("接管(shadow): %s" % taken)
        # 若主题不是「浅色」，先切到浅色
        click_theme_until('浅色')
        time.sleep(0.3)
        client.screenshot(str(shots_dir / "shot-light.png"))
        results.append(("shot-light.png", "接管视图·浅色·全展开"))

        # ---------- B) 深色（全局） ----------
        log("\n=== B) 深色主题 ===")
        click_theme_until('深色')
        time.sleep(0.6)
        client.screenshot(str(shots_dir / "shot-dark.png"))
        results.append(("shot-dark.png", "接管视图·深色"))

        # ---------- C) 工具栏特写（保留转义高亮） ----------
        log("\n=== C) 工具栏开关态 ===")
        click_theme_until('浅色')
        # 读取保留转义开关状态，仅在关闭时点击开启，保证截图里是高亮态
        JS_ESC_ON = "(function(){var b=window.__jfButtons();for(var i=0;i<b.length;i++){if(b[i].textContent.indexOf('保留转义')>=0)return {cls:b[i].className,t:b[i].title};}return null;})()"
        st0 = ev(client, JS_ESC_ON)
        log("保留转义点击前: %s" % json.dumps(st0, ensure_ascii=False))
        if not (st0 and 'jf-btn-on' in (st0.get('cls') or '')):
            r_esc = ev(client, "window.__jfClick('escape')")
            st1 = ev(client, JS_ESC_ON)
            log("保留转义点击: %s -> %s" % (r_esc, json.dumps(st1, ensure_ascii=False)))
            time.sleep(0.5)
        else:
            log("保留转义已开启")
        # 工具栏特写：只截顶部 220px
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": 1280, "height": 220, "deviceScaleFactor": 2, "mobile": False})
        time.sleep(0.3)
        client.screenshot(str(shots_dir / "shot-toolbar.png"))
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        results.append(("shot-toolbar.png", "工具栏·5按钮+保留转义高亮"))

        # ---------- D) 压缩 ----------
        log("\n=== D) 压缩模式 ===")
        click_mode_until('压缩')
        time.sleep(0.6)
        client.screenshot(str(shots_dir / "shot-compact.png"))
        results.append(("shot-compact.png", "压缩模式·单行"))

        # ---------- E) 编辑页（浅色，格式化完成） ----------
        log("\n=== E) 编辑页 ===")
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30.0)
        client.wait_for("document.readyState === 'complete' && !!document.getElementById('input')",
                        timeout=15.0)
        time.sleep(0.8)
        ev(client, JF_HELPERS)  # 编辑页无 shadow，但注入无害
        ev(client, """
        (async function () {
          var el = document.getElementById('input');
          var btn = document.getElementById('btnSample');
          if (btn) { btn.click(); } else {
            el.value = '{"a":1,"b":[true,null,"x"],"c":{"d":600653836507516928}}';
            el.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }));
          }
          await new Promise(function (r) { setTimeout(r, 1100); });
          return 'ok';
        })()
        """, timeout=30.0)
        # 编辑页从 chrome.storage 读到的主题可能是深色（B 步骤 persist 过），切回浅色
        click_theme_until('浅色')
        time.sleep(0.3)
        client.screenshot(str(docs_dir / "editor-done.png"))
        results.append(("editor-done.png", "编辑页·格式化完成"))

        # ---------- F) 编辑页·深色（全局） ----------
        log("\n=== F) 编辑页·深色 ===")
        click_theme_until('深色')
        time.sleep(0.6)
        client.screenshot(str(docs_dir / "editor-dark.png"))
        results.append(("editor-dark.png", "编辑页·全局深色"))

        # ---------- G) 编辑页·压缩（深色下更能看清单行效果） ----------
        log("\n=== G) 编辑页·压缩 ===")
        click_mode_until('压缩')
        time.sleep(0.5)
        client.screenshot(str(docs_dir / "editor-compact.png"))
        results.append(("editor-compact.png", "编辑页·压缩·单行"))

        # ---------- H) 编辑页·空状态 ----------
        log("\n=== H) 编辑页·空状态 ===")
        ev(client, "document.getElementById('btnClear').click();")
        click_theme_until('浅色')
        time.sleep(0.5)
        client.screenshot(str(docs_dir / "editor-empty.png"))
        results.append(("editor-empty.png", "编辑页·空状态"))

        # ---------- I) popup 弹窗 ----------
        log("\n=== I) popup 弹窗 ===")
        client.navigate("chrome-extension://%s/src/popup/popup.html" % ext_id, timeout=30.0)
        client.wait_for("document.readyState === 'complete'", timeout=15.0)
        time.sleep(0.6)
        # 按页面实际尺寸设视口，避免大片空白
        size = ev(client, "JSON.stringify({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})")
        size = json.loads(size)
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": max(200, size["w"]), "height": max(120, size["h"]),
                     "deviceScaleFactor": 2, "mobile": False})
        time.sleep(0.3)
        client.screenshot(str(shots_dir / "ui-popup.png"))
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        results.append(("ui-popup.png", "popup 弹窗"))

        # ---------- J) 设置页 ----------
        log("\n=== J) 设置页 ===")
        client.navigate("chrome-extension://%s/src/options/options.html" % ext_id, timeout=30.0)
        client.wait_for("document.readyState === 'complete'", timeout=15.0)
        time.sleep(0.6)
        client.screenshot(str(shots_dir / "ui-options.png"))
        results.append(("ui-options.png", "设置页"))

        # ---------- K) 编辑页·错误定位卡片 ----------
        log("\n=== K) 编辑页·错误定位 ===")
        client.navigate("chrome-extension://%s/src/editor/editor.html" % ext_id, timeout=30.0)
        client.wait_for("document.readyState === 'complete' && !!document.getElementById('input')",
                        timeout=15.0)
        time.sleep(0.8)
        ev(client, """
        (async function () {
          var el = document.getElementById('input');
          el.value = '{\\n  "code": "0",\\n  "msg" :缺少冒号\\n}';
          el.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }));
          await new Promise(function (r) { setTimeout(r, 900); });
          return !!document.querySelector('.jf-error');
        })()
        """, timeout=30.0)
        log("error card: %s" % ev(client, "!!document.querySelector('.jf-error')"))
        client.screenshot(str(docs_dir / "editor-error.png"))
        results.append(("editor-error.png", "编辑页·错误行列定位"))

        # ---------- L) 编辑页·全屏沉浸 ----------
        log("\n=== L) 编辑页·全屏沉浸 ===")
        ev(client, """
        (async function () {
          document.getElementById('btnSample').click();
          await new Promise(function (r) { setTimeout(r, 1100); });
          // CDP 环境里 requestFullscreen 会被 fullscreenchange 摘掉布局类，
          // 直接操纵等价 class（与 applyFocus(true) 效果一致）
          document.documentElement.classList.add('is-fullscreen');
          var ws = document.getElementById('workspace');
          if (ws) ws.classList.add('is-focus');
          var lbl = document.getElementById('fsLabel');
          if (lbl) lbl.textContent = '退出全屏';
          await new Promise(function (r) { setTimeout(r, 500); });
          return document.documentElement.className;
        })()
        """, timeout=30.0)
        log("fullscreen: %s" % ev(client,
            "document.documentElement.classList.contains('is-fullscreen')"))
        client.screenshot(str(docs_dir / "editor-fullscreen.png"))
        results.append(("editor-fullscreen.png", "编辑页·全屏沉浸"))

        # ---------- 结论 ----------
        log("\n" + "=" * 50)
        for name, desc in results:
            log("  ✓ %-24s %s" % (name, desc))
        log("=" * 50)
        log("[完成] 共 %d 张截图" % len(results))
        return 0
    except CDPError as exc:
        log("CDP 错误：" + str(exc))
        return 1
    finally:
        if not args.keep:
            client.close()
            # 停止浏览器
            try:
                import cdp as _cdp
            except Exception:
                pass
            try:
                from cdp import pid_path
                import os as _os
                pidf = pid_path(port)
                if pidf.exists():
                    pid = int(pidf.read_text().strip())
                    if sys.platform.startswith("win"):
                        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
