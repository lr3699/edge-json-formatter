#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-edit.py —— 验收「格式化后的 JSON 区域可编辑」。

覆盖两条互不相同的编辑路径，以及它们共用的那条回写通道：

  1) 树视图就地编辑（viewer.js）—— 双击键名 / 值，行内 input，Enter 提交
  2) 编辑模式（bigview.js + editor.js）—— 右栏换成可编辑的 CodeMirror

两者都必须把结果落回**左侧输入栏**（唯一真源），不得出现
「树改了、文本没改」的第二份状态。

用法：
    python tools/verify-edit.py --port 9381 --base http://127.0.0.1:18544 [--shots]

前置：
  · Edge 已用 --remote-debugging-port=<port> 启动
  · 本地静态服务已在 <base> 上跑着（node tools/serve.js 18544）
"""

import argparse
import json
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
from cdp import CDPClient, CDPError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "shots" / "edit"

SAMPLE = json.dumps({
    "code": "0",
    "msg": "success",
    "count": 3,
    "paid": True,
    "refunded": None,
    "data": {
        "orderId": "600653836507516928",
        "amount": 128.5,
        "tags": ["vip", "2026-09", "nested"],
        "buyer": {"id": 10086, "nickname": "张三"},
    },
}, ensure_ascii=False, separators=(",", ":"))

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  " + str(detail)) if detail else ""))


def wait_until(ev, cond, timeout=20, poke=None):
    """轮询等条件成立。

    不能只依赖 CDPClient.wait_for：本工具的关键路径有 requestAnimationFrame
    （大文档排版），而被遮挡/非前台窗口的 rAF 会被 Chromium 节流甚至暂停，
    于是「明明已经进了编辑模式，却一直停在解析中…」。poke 每轮把页面顶到前台，
    逼出一帧，让 rAF 有得跑。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ev(cond):
            return True
        if poke:
            try:
                poke()
            except Exception:
                pass
        time.sleep(0.25)
    return False


HELPERS = r"""
window.__t = {
  setInput: function (text) {
    var ta = document.getElementById('input');
    ta.hidden = false;
    ta.value = text;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  },
  left: function () { return document.getElementById('input').value; },
  leftOk: function () { try { JSON.parse(window.__t.left()); return true; } catch (e) { return false; } },
  rows: function () { return document.querySelectorAll('.jf-row').length; },
  cells: function () {
    var out = [], rows = document.querySelectorAll('.jf-row');
    for (var i = 0; i < rows.length; i++) {
      var k = rows[i].querySelector('.jf-key'), v = rows[i].querySelector('.jf-val');
      if (k || v) out.push((k ? k.textContent : '') + '=' + (v ? v.textContent : ''));
    }
    return out.join('|');
  },
  rowByText: function (txt) {
    var rows = document.querySelectorAll('.jf-row');
    for (var i = 0; i < rows.length; i++) {
      if ((rows[i].textContent || '').indexOf(txt) >= 0) return rows[i];
    }
    return null;
  },
  rowByKey: function (key) {
    var rows = document.querySelectorAll('.jf-row');
    for (var i = 0; i < rows.length; i++) {
      var k = rows[i].querySelector('.jf-key');
      if (k && k.textContent === '"' + key + '"') return rows[i];
    }
    return null;
  },
  dblVal: function (key) {
    var r = window.__t.rowByKey(key);
    if (!r) return 'NO_ROW:' + key;
    var v = r.querySelector('.jf-val');
    if (!v) return 'NO_VAL:' + key;
    v.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }));
    return !!document.querySelector('.jf-edit');
  },
  dblKey: function (key) {
    var r = window.__t.rowByKey(key);
    if (!r) return 'NO_ROW:' + key;
    var k = r.querySelector('.jf-key');
    k.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }));
    return !!document.querySelector('.jf-edit');
  },
  typed: function () {
    var sel = document.querySelector('.jf-edit-type');
    return sel ? sel.value : null;
  },
  setType: function (type) {
    var sel = document.querySelector('.jf-edit-type');
    if (!sel) return false;
    sel.value = type;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  },
  commit: function (value) {
    var inp = document.querySelector('.jf-edit-input');
    if (!inp) return false;
    inp.value = value;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    return true;
  },
  esc: function () {
    var inp = document.querySelector('.jf-edit-input');
    if (!inp) return false;
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    return true;
  },
  open: function () { return !!document.querySelector('.jf-edit'); },
  hint: function () { var h = document.querySelector('.jf-edit-hint'); return h ? h.textContent : ''; },
  status: function () {
    var p = document.getElementById('pillText'), m = document.getElementById('msg');
    return (p ? p.textContent : '') + ' | ' + (m ? m.textContent : '');
  },
  pill: function () { return document.getElementById('pillText').textContent; },
  bigDoc: function () {
    var h = document.getElementById('bigView');
    return (h && h.__jfView) ? h.__jfView.state.doc.toString() : null;
  },
  bigEdit: function (find, repl) {
    var h = document.getElementById('bigView');
    var v = h && h.__jfView;
    if (!v) return 'NO_VIEW';
    var doc = v.state.doc.toString();
    var at = doc.indexOf(find);
    if (at < 0) return 'NOT_FOUND:' + find;
    v.dispatch({ changes: { from: at, to: at + find.length, insert: repl } });
    return 'OK';
  },
  cmEditable: function () {
    var c = document.querySelector('#bigView .cm-content');
    return c ? c.getAttribute('contenteditable') : null;
  }
};
true;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9381)
    ap.add_argument("--base", default="http://127.0.0.1:18544")
    ap.add_argument("--shots", action="store_true", help="产出截图到 docs/shots/edit/")
    args = ap.parse_args()

    cdp = CDPClient(port=args.port)
    if not cdp.is_alive():
        print("CDP 端口 %d 不通：请先启动 Edge（--remote-debugging-port=%d）" % (args.port, args.port))
        return 2

    def ev(expr, timeout=None):
        return cdp.evaluate(expr, timeout=timeout).get("value")

    cdp.ensure_page()
    try:
        cdp.send("Emulation.setDeviceMetricsOverride",
                 {"width": 1360, "height": 860, "deviceScaleFactor": 1, "mobile": False})
    except CDPError:
        pass

    if not cdp.navigate(args.base + "/src/editor/editor.html"):
        print("页面加载超时：" + args.base + "/src/editor/editor.html")
        return 2
    # 顶到前台：后台/被遮挡的窗口 rAF 会被节流，而大文档排版正是跑在 rAF 里
    try:
        cdp.send("Page.bringToFront")
    except CDPError:
        pass
    def poke():
        """逼出一帧，让被节流的 rAF 有机会执行。"""
        try:
            cdp.send("Page.bringToFront")
            cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 5})
        except CDPError:
            pass
    cdp.wait_for("!!document.getElementById('input')", timeout=15)
    ev(HELPERS)
    ev("window.__errs=[];window.addEventListener('error',function(e){window.__errs.push('error: '+e.message)});"
       "window.addEventListener('unhandledrejection',function(e){window.__errs.push('rejection: '+String(e.reason))});true")

    print("\n== 1. 基础：粘贴 → 树视图 ==")
    ev("window.__t.setInput(%s)" % json.dumps(SAMPLE))
    cdp.wait_for("window.__t.rows() > 6", timeout=10)
    check("树视图渲染出行", (ev("window.__t.rows()") or 0) > 6, "%s 行" % ev("window.__t.rows()"))
    check("键/字符串/数字/布尔四类高亮都在",
          ev("!!document.querySelector('.jf-key') && !!document.querySelector('.jf-str')"
             " && !!document.querySelector('.jf-num') && !!document.querySelector('.jf-bool')"))
    if args.shots:
        OUT.mkdir(parents=True, exist_ok=True)
        cdp.screenshot(str(OUT / "01-tree.png"))

    print("\n== 2. 树视图就地编辑：改值 ==")
    check("双击值打开行内编辑器", ev("window.__t.dblVal('orderId')") is True)
    check("类型下拉预置为字符串", ev("window.__t.typed()") == "string")
    ev("window.__t.commit('600653836507516999')")
    cdp.wait_for("window.__t.left().indexOf('600653836507516999') >= 0", timeout=5)
    check("新值回写到左侧输入栏", "600653836507516999" in (ev("window.__t.left()") or ""))
    check("左侧文本仍是合法 JSON", ev("window.__t.leftOk()") is True)
    check("树上同步显示新值", "600653836507516999" in (ev("window.__t.cells()") or ""))
    check("提交后编辑器自动关闭", ev("window.__t.open()") is False)

    print("\n== 3. 树视图就地编辑：改键名 ==")
    ev("window.__t.dblKey('nickname')")
    ev("window.__t.commit('nickName')")
    cdp.wait_for("window.__t.left().indexOf('nickName') >= 0", timeout=5)
    check("键名回写到左侧", "nickName" in (ev("window.__t.left()") or ""))
    check("树上显示新键名", '"nickName"' in (ev("window.__t.cells()") or ""))

    print("\n== 4. 树视图就地编辑：同层重名键要拦住 ==")
    # 必须挑**同层**的键：code 与 count 都挂在根对象上，才是真正的重名；
    # 早先写成 orderId → count 是错的（orderId 在 data 里，跨层改名本来就该允许）。
    ev("window.__t.dblKey('code')")
    ev("window.__t.commit('count')")
    check("重名键被拒绝并给出提示", "同名" in (ev("window.__t.hint()") or ""), ev("window.__t.hint()"))
    check("被拒后编辑器仍开着（不静默丢失输入）", ev("window.__t.open()") is True)
    ev("window.__t.esc()")
    check("Esc 取消编辑", ev("window.__t.open()") is False)
    check("被拒后原键名仍在", '"code"' in (ev("window.__t.left()") or ""))

    print("\n== 5. 树视图就地编辑：换类型（数字 → 字符串） ==")
    ev("window.__t.dblVal('count')")
    ev("window.__t.setType('string')")
    ev("window.__t.commit('abc')")
    cdp.wait_for("window.__t.left().indexOf('\"abc\"') >= 0", timeout=5)
    check("类型切换后写成字符串字面量", '"count": "abc"' in (ev("window.__t.left()") or ""))

    print("\n== 6. 树视图就地编辑：非法数字要拦住 ==")
    ev("window.__t.dblVal('amount')")
    ev("window.__t.setType('number')")
    ev("window.__t.commit('01.2.3')")
    check("非法数字被拒绝", "数字" in (ev("window.__t.hint()") or ""), ev("window.__t.hint()"))
    ev("window.__t.esc()")
    check("取消后 amount 仍是原值", '"amount": 128.5' in (ev("window.__t.left()") or ""))

    print("\n== 7. 编辑模式：右栏换成可编辑文本 ==")
    ev("document.getElementById('btnEdit').click()")
    # 排版是在 rAF 里跑的：必须等文档真的排完（doc 非空）再断言，
    # 否则 CM 实例刚建好、doc 还是空的，会误判成「没切过去」。
    ok = wait_until(ev, "(function(){var h=document.getElementById('bigView');"
                        "return !!(h && !h.hidden && h.__jfView && h.__jfView.state.doc.length);})()",
                    timeout=25, poke=poke)
    check("右栏切到 CodeMirror", ev("!!window.__t.bigDoc()") is True and ok)
    check("顶栏按钮进入按下态",
          ev("document.getElementById('btnEdit').getAttribute('aria-pressed')") == "true")
    check("按钮文案变成「完成编辑」",
          ev("document.getElementById('editLabel').textContent") == "完成编辑")
    check("CodeMirror 内容可编辑", ev("window.__t.cmEditable()") == "true")
    check("右栏文本就是格式化结果",
          '"orderId": "600653836507516999"' in (ev("window.__t.bigDoc()") or ""))
    check("状态带进入「编辑中」", ev("window.__t.pill()") == "编辑中", ev("window.__t.status()"))
    if args.shots:
        cdp.screenshot(str(OUT / "02-edit-mode.png"))

    print("\n== 8. 编辑模式：改内容 → 实时回写左栏 ==")
    check("在 CodeMirror 里改一个数字", ev("window.__t.bigEdit('128.5', '256')") == "OK")
    cdp.wait_for("window.__t.left().indexOf('\"amount\": 256') >= 0", timeout=5)
    check("改动回写到左侧输入栏", '"amount": 256' in (ev("window.__t.left()") or ""))
    check("左栏仍是合法 JSON", ev("window.__t.leftOk()") is True)

    print("\n== 9. 编辑模式：写成非法 JSON 要给出行列 ==")
    ev("window.__t.bigEdit('\"msg\": \"success\",', '\"msg\": success,,')")
    cdp.wait_for("window.__t.pill() === '格式有误'", timeout=6)
    check("标为格式有误", ev("window.__t.pill()") == "格式有误")
    check("提示里带行号列号", "行" in (ev("window.__t.status()") or ""), ev("window.__t.status()"))
    if args.shots:
        cdp.screenshot(str(OUT / "03-edit-invalid.png"))
    ev("window.__t.bigEdit('\"msg\": success,,', '\"msg\": \"success\",')")
    cdp.wait_for("window.__t.pill() === '编辑中'", timeout=6)
    check("改回合法后恢复「编辑中」", ev("window.__t.pill()") == "编辑中")

    print("\n== 10. 退出编辑 → 回到只读树，内容不丢 ==")
    ev("document.getElementById('btnEdit').click()")
    cdp.wait_for("document.getElementById('bigView').hidden", timeout=10)
    check("退出编辑模式收起 CodeMirror", ev("document.getElementById('bigView').hidden") is True)
    check("顶栏按钮恢复",
          ev("document.getElementById('btnEdit').getAttribute('aria-pressed')") == "false")
    cdp.wait_for("window.__t.rows() > 6", timeout=10)
    check("树视图重新出现", (ev("window.__t.rows()") or 0) > 6)
    # 光有 .jf-row 不算数：它们可能正渲染在一个 hidden 的宿主里（右栏看着就是空白）。
    # 这条是「点完成编辑后右栏空白」那个 bug 的回归哨兵。
    check("树视图宿主可见（不是藏在 hidden 里渲染）",
          ev("document.getElementById('viewer').hidden") is False)
    check("树视图有实际渲染高度",
          (ev("document.getElementById('viewer').getBoundingClientRect().height") or 0) > 100,
          "%s px" % ev("document.getElementById('viewer').getBoundingClientRect().height"))
    left = ev("window.__t.left()") or ""
    check("前面几步的改动都还在（值 / 键 / 类型 / 编辑模式内改的）",
          "600653836507516999" in left and "nickName" in left
          and '"count": "abc"' in left and '"amount": 256' in left)
    if args.shots:
        cdp.screenshot(str(OUT / "04-back-to-tree.png"))

    print("\n== 11. 清空 ==")
    ev("document.getElementById('btnClear').click()")
    cdp.wait_for("document.getElementById('viewer').hidden", timeout=5)
    check("清空后回到欢迎页", ev("document.getElementById('welcome').hidden") is False)
    check("清空后「编辑」按钮不可点", ev("document.getElementById('btnEdit').disabled") is True)

    errs = ev("window.__errs") or []
    check("页面无 JS 异常", not errs, errs[:3])

    print("\n" + "=" * 52)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
