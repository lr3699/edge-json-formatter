#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-editor.py —— 在真实 Edge + 已加载扩展的环境里验收「粘贴 JSON 格式化」页。

做三件事：
  1. 从 CDP 的 target 列表里找出解压扩展的 ID（不动 manifest、不用猜 hash）；
  2. 打开扩展内的 editor.html，模拟一次「粘贴」；
  3. 抓关键帧截图 + 读取 .jf-row 的 animation-name / animation-delay，
     确认逐行入场动效确实在跑，并回收页面里的 JS 报错。

前置：Edge 已带 --load-extension=dist/unpacked --remote-debugging-port=<port> 启动。

用法：
    python tools/verify-editor.py [--port 9334] [--outdir docs]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path(
    os.environ.get(
        "CDP_SKILL_SCRIPTS",
        Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts",
    )
)
sys.path.insert(0, str(SKILL_SCRIPTS))

try:
    from cdp import CDPClient, CDPError  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print("无法导入 cdp.py（来自 %s）：%s" % (SKILL_SCRIPTS, exc), file=sys.stderr)
    raise SystemExit(1)


# 页面加载前就装上错误收集器，否则初始化阶段的报错会漏掉
ERROR_HOOK = """
window.__errs = [];
window.addEventListener('error', function (e) {
  window.__errs.push('error: ' + (e.message || e.type));
});
window.addEventListener('unhandledrejection', function (e) {
  window.__errs.push('rejection: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason)));
});
var _ce = console.error;
console.error = function () {
  window.__errs.push('console.error: ' + Array.prototype.join.call(arguments, ' '));
  _ce.apply(console, arguments);
};
"""

SAMPLE = json.dumps({
    "code": "0",
    "msg": "success",
    "data": {
        "orderId": "600653836507516928",
        "amount": 128.5,
        "paid": True,
        "refunded": None,
        "tags": ["vip", "2026-09"],
        "buyer": {
            "id": 10086,
            "nickname": "张三",
            "remark": '带"引号"、制表符\\t 和换行的备注',
        },
        "items": [
            {"sku": "A-1", "name": "机械键盘", "qty": 1, "price": 399},
            {"sku": "B-2", "name": "显示器支架", "qty": 2, "price": 89},
        ],
    },
    "ts": 1784173433013,
}, ensure_ascii=False, indent=2)


def paste_js(text, sample_ms=40, samples=40):
    """在页面里完成「粘贴 → 等防抖 → 渲染」，并在动画期间**在页面内**持续采样。

    为什么不在外面 sleep 再读一次：CDP 往返本身有延迟，单次采样很容易
    早一步或晚一步错过动画窗口，从而误判「动效没生效」。
    在页面内用 setInterval 采样拿到的是真实时间线。
    """
    return """
    (async function () {
      var el = document.getElementById('input');
      var host = document.getElementById('viewer');
      var out = { inputTypeSeen: null, samples: 0, freshCount: 0,
                  animNames: {}, delays: {}, reducedMotion:
                  window.matchMedia('(prefers-reduced-motion: reduce)').matches };
      el.addEventListener('input', function (e) {
        if (out.inputTypeSeen === null) out.inputTypeSeen = e.inputType;
      }, true);
      el.focus();
      el.value = %s;
      el.dispatchEvent(new InputEvent('input', {
        inputType: 'insertFromPaste', bubbles: true, data: el.value
      }));

      await new Promise(function (resolve) {
        var n = 0;
        var timer = setInterval(function () {
          var rows = host.querySelectorAll('.jf-row');
          if (host.className.indexOf('is-fresh') >= 0) {
            out.freshCount++;
            if (rows[0]) {
              var cs = getComputedStyle(rows[0]);
              out.animNames[cs.animationName] = (out.animNames[cs.animationName] || 0) + 1;
              out.delays['r0'] = cs.animationDelay;
            }
            if (rows[3]) out.delays['r3'] = getComputedStyle(rows[3]).animationDelay;
          }
          out.samples++;
          if (++n >= %d) { clearInterval(timer); resolve(); }
        }, %d);
      });

      var rows = host.querySelectorAll('.jf-row');
      out.finalRows = rows.length;
      out.finalAnim = rows[0] ? getComputedStyle(rows[0]).animationName : null;
      out.pill = document.getElementById('pillText').textContent;
      out.welcomeHidden = document.getElementById('welcome').hidden;
      return JSON.stringify(out);
    })()
    """ % (json.dumps(text), samples, sample_ms)


def find_extension_id(client):
    """解压扩展的 ID 由安装路径的 hash 决定，别去猜——直接在 target 列表里找。

    注意：Edge 自带一堆扩展（PDF、购物、QQ 浏览器导入等）也会出现在列表里，
    随便取第一个 chrome-extension:// 会拿到别人的 ID，然后导航到 ERR_FILE_NOT_FOUND。
    所以优先认自己的 service worker 路径。
    """
    candidates = []
    for target in client.targets():
        url = target.get("url") or ""
        if url.startswith("chrome-extension://"):
            candidates.append((url.split("/")[2], url))

    for ext_id, url in candidates:
        if url.endswith("/src/background/service-worker.js"):
            return ext_id, url
    for ext_id, url in candidates:
        if "/src/" in url:
            return ext_id, url
    print("候选扩展：%s" % candidates, file=sys.stderr)
    return None, None


def navigate_checked(client, url, attempts=3):
    """导航到扩展内页面；命中错误页就重试（扩展资源首次读取偶尔会被内容校验挡住）。"""
    last = ""
    for i in range(attempts):
        client.navigate(url, timeout=30.0)
        last = client.page_url() or ""
        if not last.startswith("chrome-error"):
            return True
        time.sleep(0.8)
    print("导航失败：%s（最后停在 %s）" % (url, last), file=sys.stderr)
    return False


def ev(client, expr, timeout=30.0):
    res = client.send("Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True,
        "userGesture": True,
    }, timeout=timeout)
    if res.get("exceptionDetails"):
        exc = res["exceptionDetails"]
        desc = (exc.get("exception") or {}).get("description") or exc.get("text")
        raise RuntimeError("页面 JS 异常：%s" % desc)
    return res.get("result", {}).get("value")


def report_problems(problems):
    """收尾统一汇报：有问题打印清单并返回非零，干净则返回 0。"""
    if problems:
        print("\n[失败] 共 %d 项未通过：" % len(problems), file=sys.stderr)
        for item in problems:
            print("  - %s" % item, file=sys.stderr)
        return 6
    print("\n[通过] 入场动效 / 全屏沉浸 / 闪动回归 全部符合预期")
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(prog="verify-editor.py")
    p.add_argument("--port", type=int, default=9334)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--outdir", default="docs")
    p.add_argument("--static-url", default=None,
                   help="直接验证这个 URL（脱离扩展的静态预览页），跳过扩展 ID 探测")
    args = p.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    client = CDPClient(host=args.host, port=args.port, timeout=30.0)
    problems = []
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: %s 无响应" % client.base_http)
            return 2

        ext_id = None
        if args.static_url:
            url = args.static_url
            print("模式    : 静态预览（不走扩展）")
            print("目标 URL: %s" % url)
        else:
            ext_id, sw_url = find_extension_id(client)
            if not ext_id:
                print("找不到 chrome-extension:// target —— 扩展可能没加载成功", file=sys.stderr)
                return 3
            print("扩展 ID  : %s" % ext_id)
            print("命中 URL : %s" % sw_url)
            url = "chrome-extension://%s/src/editor/editor.html" % ext_id

        client.ensure_page()
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_HOOK})
        if not navigate_checked(client, url):
            return 4
        client.send("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 940, "deviceScaleFactor": 1, "mobile": False,
        })

        ready = client.wait_for(
            "document.readyState === 'complete' && !!document.getElementById('input')",
            timeout=20.0,
        )
        if not ready:
            print("页面没就绪：%s" % client.page_url(), file=sys.stderr)
            return 4
        time.sleep(1.2)  # 等 aurora / panelIn 入场动画停下来再截空状态

        # --- 空状态 ---
        client.screenshot(str(outdir / "editor-empty.png"))
        print("空状态截图 : %s" % (outdir / "editor-empty.png"))

        # --- 模拟粘贴 + 页面内时间线采样（inputType 决定要不要播动效）---
        anim = json.loads(ev(client, paste_js(SAMPLE)))

        # 再粘一次，抓动画进行中的一帧（纯视觉留档；结论以上面的采样为准）
        ev(client, """
        (function () {
          var el = document.getElementById('input');
          el.value = '';
          el.dispatchEvent(new InputEvent('input', { inputType: 'deleteContentBackward', bubbles: true }));
          return true;
        })()
        """)
        time.sleep(0.9)
        ev(client, """
        (function () {
          var el = document.getElementById('input');
          var text = %s;
          el.focus();
          el.value = text;
          el.dispatchEvent(new InputEvent('input', {
            inputType: 'insertFromPaste', bubbles: true, data: text
          }));
          return true;
        })()
        """ % json.dumps(SAMPLE))
        time.sleep(0.30)
        client.screenshot(str(outdir / "editor-anim.png"))
        print("动效帧截图 : %s" % (outdir / "editor-anim.png"))

        # 等动效收尾（is-fresh 摘掉）再截，否则可能截到重绘中间态（整屏空白）
        client.wait_for(
            "!document.getElementById('viewer').classList.contains('is-fresh')",
            timeout=10.0,
        )
        time.sleep(0.6)
        ev(client, "void document.body.offsetHeight")  # 逼一次同步布局再截
        client.screenshot(str(outdir / "editor-done.png"))
        print("完成态截图 : %s" % (outdir / "editor-done.png"))

        print("\n--- 动效时间线（页面内采样）---")
        print(json.dumps(anim, ensure_ascii=False, indent=2))

        # --- 最终诊断 ---
        # 趁示例 JSON 还挂在页面上时读，rows / 字体这些字段才有代表性：
        # 后面的闪动回归会把输入换成短 JSON，放在那之后再读就只剩几行了。
        diag = ev(client, """
        (function () {
          var host = document.getElementById('viewer');
          var rows = host.querySelectorAll('.jf-row');
          var cs = rows[0] ? getComputedStyle(rows[0]) : null;
          function txt(id) { var n = document.getElementById(id); return n ? n.textContent.trim() : null; }
          var wrap = document.querySelector('.workspace');
          return JSON.stringify({
            url: location.href,
            rows: rows.length,
            rowFontSize: cs ? cs.fontSize : null,
            rowFontFamily: cs ? cs.fontFamily.slice(0, 46) : null,
            rowFontWeight: cs ? cs.fontWeight : null,
            rowOpacity: cs ? cs.opacity : null,
            rowAnimationAfter: cs ? cs.animationName : null,
            hostClass: host.className,
            split: getComputedStyle(document.documentElement).getPropertyValue('--split').trim(),
            workspaceCols: wrap ? getComputedStyle(wrap).gridTemplateColumns : null,
            pill: txt('pillText'),
            msg: txt('msg'),
            stats: txt('stats'),
            welcomeHidden: document.getElementById('welcome').hidden,
            optionsBtnHidden: document.getElementById('btnOptions').hidden,
            floatingRows: (function () {
              var n = 0;
              rows.forEach(function (r) {
                if (getComputedStyle(r).position === 'absolute' || getComputedStyle(r).position === 'fixed') n++;
              });
              return n;
            })(),
            errors: window.__errs || []
          });
        })()
        """)
        print("\n--- 最终状态 ---")
        print(json.dumps(json.loads(diag), ensure_ascii=False, indent=2))

        # --- 全屏 / 沉浸模式：进入 ---
        # 注意：无头环境里 requestFullscreen() 会被拒，但本页是「先切布局、再试全屏 API」，
        # 所以 is-fullscreen / is-focus 这两个类在任何环境下都应该加上——正好用它当断言。
        fs_on = json.loads(ev(client, """
        (async function () {
          var btn = document.getElementById('btnFullscreen');
          btn.click();
          await new Promise(function (r) { setTimeout(r, 520); });
          var root = document.documentElement;
          var wrap = document.getElementById('workspace');
          var inp = document.getElementById('panelInput');
          return JSON.stringify({
            htmlFs: root.classList.contains('is-fullscreen'),
            wrapFocus: wrap.classList.contains('is-focus'),
            label: (document.getElementById('fsLabel') || {}).textContent,
            pressed: btn.getAttribute('aria-pressed'),
            title: btn.title,
            cols: getComputedStyle(wrap).gridTemplateColumns,
            inputDisplay: inp ? getComputedStyle(inp).display : null,
            realFullscreen: !!document.fullscreenElement,
            errors: window.__errs || []
          });
        })()
        """))
        client.screenshot(str(outdir / "editor-fullscreen.png"))
        print("\n--- 全屏 / 沉浸（进入后）---")
        print(json.dumps(fs_on, ensure_ascii=False, indent=2))
        print("全屏截图 : %s" % (outdir / "editor-fullscreen.png"))

        # --- 全屏 / 沉浸模式：按 F 退出 ---
        fs_off = json.loads(ev(client, """
        (async function () {
          document.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'f', bubbles: true
          }));
          await new Promise(function (r) { setTimeout(r, 520); });
          var root = document.documentElement;
          var wrap = document.getElementById('workspace');
          var inp = document.getElementById('panelInput');
          return JSON.stringify({
            htmlFs: root.classList.contains('is-fullscreen'),
            wrapFocus: wrap.classList.contains('is-focus'),
            label: (document.getElementById('fsLabel') || {}).textContent,
            pressed: document.getElementById('btnFullscreen').getAttribute('aria-pressed'),
            inputDisplay: inp ? getComputedStyle(inp).display : null,
            errors: window.__errs || []
          });
        })()
        """))
        print("\n--- 全屏 / 沉浸（按 F 退出后）---")
        print(json.dumps(fs_off, ensure_ascii=False, indent=2))

        # --- 闪动回归：连打时输出面板不该被反复加/摘 class，胶囊圆点不该有循环动画 ---
        # 之前的「窗口闪动」来自三处：面板 ::before 扫描条、面板 box-shadow 环、胶囊圆点
        # 的 infinite pulse。这里用 MutationObserver 盯住面板 class，并直接读胶囊圆点的
        # animationName —— 只要它是 none，就说明循环脉冲确实没了。
        flick = json.loads(ev(client, """
        (async function () {
          var out = document.getElementById('panelOutput');
          var pill = document.getElementById('statusPill');
          var dot = document.querySelector('.pill-dot');
          var seen = { busy: 0, flash: 0, panelClassMutations: 0 };
          var mo = new MutationObserver(function (muts) {
            muts.forEach(function (m) {
              if (m.attributeName !== 'class') return;
              seen.panelClassMutations++;
              var cls = String(out.className);
              if (cls.indexOf('is-busy') >= 0) seen.busy++;
              if (cls.indexOf('is-flash') >= 0) seen.flash++;
            });
          });
          mo.observe(out, { attributes: true, attributeFilter: ['class'] });

          var el = document.getElementById('input');
          el.focus();
          for (var i = 0; i < 12; i++) {
            el.value = '{"n":1,"i":' + i + ',"pad":"' + 'x'.repeat(i) + '"}';
            el.dispatchEvent(new InputEvent('input', {
              inputType: 'insertText', bubbles: true, data: String(i)
            }));
            await new Promise(function (r) { setTimeout(r, 55); });
          }
          // 采样「解析中」状态下的胶囊圆点动画
          var dotBusy = getComputedStyle(dot).animationName;
          await new Promise(function (r) { setTimeout(r, 700); });
          var dotOk = getComputedStyle(dot).animationName;
          mo.disconnect();

          // 顺便确认已经删掉的扫描条伪元素确实不存在
          var before = getComputedStyle(out, '::before');
          return JSON.stringify({
            panelIsBusySeen: seen.busy,
            panelIsFlashSeen: seen.flash,
            dotAnimBusy: dotBusy,
            dotAnimIdle: dotOk,
            panelBeforeContent: before ? before.content : null,
            pillClass: pill.className,
            pillText: document.getElementById('pillText').textContent,
            errors: window.__errs || []
          });
        })()
        """))
        print("\n--- 闪动回归 ---")
        print(json.dumps(flick, ensure_ascii=False, indent=2))

        # --- 断言 ---
        if not fs_on.get("htmlFs") or not fs_on.get("wrapFocus"):
            problems.append("点击全屏按钮后 html.is-fullscreen / .workspace.is-focus 未同时生效：%s" % fs_on)
        if fs_on.get("label") != "退出全屏":
            problems.append("全屏后按钮文案应变为「退出全屏」，实际：%r" % fs_on.get("label"))
        if fs_on.get("inputDisplay") != "none":
            problems.append("沉浸模式下输入面板应隐藏，实际 display=%r" % fs_on.get("inputDisplay"))
        if fs_off.get("htmlFs") or fs_off.get("wrapFocus"):
            problems.append("按 F 后沉浸布局未收起：%s" % fs_off)
        if fs_off.get("label") != "全屏":
            problems.append("退出全屏后按钮文案应回到「全屏」，实际：%r" % fs_off.get("label"))
        if fs_off.get("inputDisplay") == "none":
            problems.append("退出沉浸后输入面板仍隐藏：%s" % fs_off)

        if flick.get("panelIsBusySeen") or flick.get("panelIsFlashSeen"):
            problems.append("输出面板仍被加上 is-busy / is-flash（闪动源）：%s" % flick)
        for key in ("dotAnimBusy", "dotAnimIdle"):
            if flick.get(key) not in (None, "none"):
                problems.append("胶囊圆点仍在跑动画（%s=%r）" % (key, flick.get(key)))
        if flick.get("panelBeforeContent") not in (None, "none", '""'):
            problems.append("输出面板 ::before 扫描条仍在：%r" % flick.get("panelBeforeContent"))

        if anim.get("freshCount", 0) == 0:
            print("\n[失败] 整段采样里 is-fresh 从未出现 —— 入场动效没有触发", file=sys.stderr)
            return 5
        if "rowIn" not in anim.get("animNames", {}):
            print("\n[失败] 行上没有跑 rowIn 动画：%s" % anim.get("animNames"), file=sys.stderr)
            return 5
        delays = anim.get("delays", {})
        if delays.get("r0") != delays.get("r3"):
            pass  # 错落延迟生效（r0/r3 不同）
        elif delays.get("r0") and delays.get("r3"):
            print("\n[警告] r0 与 r3 的 animation-delay 相同，错落效果可能没生效：%s" % delays,
                  file=sys.stderr)

        # --- 错误态 ---
        bad = json.dumps('{\n  "code": 0,\n  "msg": ,\n  "data": {}\n}')
        ev(client, """
        (function () {
          var el = document.getElementById('input');
          el.focus();
          el.value = %s;
          el.dispatchEvent(new InputEvent('input', {
            inputType: 'insertFromPaste', bubbles: true
          }));
          return true;
        })()
        """ % bad)
        time.sleep(0.9)
        err = ev(client, """
        (function () {
          function txt(id) { var n = document.getElementById(id); return n ? n.textContent.trim() : null; }
          var marked = document.querySelectorAll('.jf-err-caret, .jf-error, .jf-err, [class*="jf-err"]');
          return JSON.stringify({
            pill: txt('pillText'),
            msg: txt('msg'),
            markedNodes: marked.length,
            errors: window.__errs || []
          });
        })()
        """)
        client.screenshot(str(outdir / "editor-error.png"))
        print("\n--- 错误态 ---")
        print(err)
        print("错误态截图 : %s" % (outdir / "editor-error.png"))

        # --- 入口页：popup / options 能渲染，options 上的按钮能拉起编辑页 ---
        if not ext_id:
            print("\n（静态预览模式，跳过 popup / options 入口检查）")
            return report_problems(problems)

        print("\n--- 入口页 ---")
        for label, page in (("popup", "src/popup/popup.html"),
                            ("options", "src/options/options.html")):
            purl = "chrome-extension://%s/%s" % (ext_id, page)
            if not navigate_checked(client, purl):
                print("%s: 导航失败" % label)
                continue
            client.wait_for("document.readyState === 'complete'", timeout=15.0)
            time.sleep(0.7)
            info = ev(client, """
            (function () {
              function txt(id) { var n = document.getElementById(id); return n ? n.textContent.trim() : null; }
              return JSON.stringify({
                title: document.title,
                hasPasteBtn: !!document.getElementById('btnPaste'),
                hasEditorBtn: !!document.getElementById('btnOpenEditor'),
                version: txt('version'),
                errors: window.__errs || []
              });
            })()
            """)
            client.screenshot(str(outdir / ("shot-%s.png" % label)))
            print("%s: %s" % (label, info))

        # 点 options 上的按钮，应新开（或聚焦）一个 editor 标签页
        if navigate_checked(client, "chrome-extension://%s/src/options/options.html" % ext_id):
            client.wait_for("!!document.getElementById('btnOpenEditor')", timeout=10.0)
            client.click("#btnOpenEditor")
            time.sleep(1.5)
            opened = [t.get("url") for t in client.targets()
                      if "editor.html" in (t.get("url") or "")]
            print("点击入口按钮后，编辑页标签数 = %d" % len(opened))
            for u in opened:
                print("  " + u)
        return report_problems(problems)
    except CDPError as exc:
        print("CDP 错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
