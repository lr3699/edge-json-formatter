#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe-toolbar.py —— 对比「小文档 / 大文档」两种情况下右栏工具条里到底有哪些按钮。

用途：排查「大 JSON 格式化后某个按钮不见了」这类反馈，先把两种情况的
DOM 事实摆出来，再谈改哪里。

    python tools/probe-toolbar.py --port 9333 --url http://127.0.0.1:18544/src/editor/editor.html
"""

import argparse
import json
import os
import sys
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


# 注入 JSON：小文档 ~2KB，大文档约 1.6MB（超过 editor.js 的 BIG_MIN_CHARS = 600KB）
INJECT = r"""
(async function () {
  var MODE = __MODE__;
  var obj;
  if (MODE === 'small') {
    obj = { ok: true, name: '小文档', list: [1, 2, 3], nested: { a: 'x', b: 'y' } };
  } else {
    var arr = [];
    for (var i = 0; i < 12000; i++) {
      arr.push({
        id: 'ORD' + i,
        orderId: '6006538365075169' + (i % 100),
        name: '订单-' + i,
        amount: (i * 37) % 99991 + 0.5,
        tags: ['a', 'b', 'c'],
        nested: { city: '深圳', zip: '518000', ok: i % 2 === 0 }
      });
    }
    obj = { total: arr.length, rows: arr };
  }
  var text = JSON.stringify(obj, null, 2);
  var inp = document.getElementById('input');
  inp.value = text;
  inp.dispatchEvent(new Event('input', { bubbles: true }));

  await new Promise(function (r) { setTimeout(r, 1600); });

  function visible(elm) {
    if (!elm) return false;
    if (elm.hidden) return false;
    var cs = getComputedStyle(elm);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    return elm.offsetWidth > 0 || elm.offsetHeight > 0;
  }
  var out = { mode: MODE, chars: text.length, panels: {}, groups: [] };
  ['viewer', 'bigView', 'welcome'].forEach(function (id) {
    var e = document.getElementById(id);
    out.panels[id] = visible(e);
  });
  function dump(name, root) {
    if (!root) return;
    var btns = root.querySelectorAll('button');
    if (!btns.length) return;
    var list = [];
    for (var i = 0; i < btns.length; i++) {
      var el = btns[i];
      list.push({
        text: (el.textContent || '').trim(),
        id: el.id || '',
        cls: el.className,
        visible: visible(el)
      });
    }
    out.groups.push({ where: name, count: list.length, buttons: list });
  }
  dump('顶栏 .topbar', document.querySelector('.topbar'));
  dump('输入面板头 .panel-input .panel-head', document.querySelector('.panel-input .panel-head'));
  dump('右栏 .panel-output', document.querySelector('.panel-output'));
  dump('右栏footer .panel-foot-output', document.querySelector('.panel-foot-output'));
  return JSON.stringify(out);
})()
"""


def run(client, mode):
    js = INJECT.replace("__MODE__", json.dumps(mode))
    res = client.send(
        "Runtime.evaluate",
        {"expression": js, "returnByValue": True, "awaitPromise": True, "userGesture": True},
        timeout=120,
    )
    if res.get("exceptionDetails"):
        raise RuntimeError(str(res["exceptionDetails"])[:900])
    return json.loads(res["result"]["value"])


def show(res):
    print("=" * 68)
    print("模式: %s    输入字符数: %s" % (res["mode"], res.get("chars")))
    print("可见面板: " + ", ".join(
        "%s=%s" % (k, "是" if v else "否") for k, v in (res.get("panels") or {}).items()))
    for g in res.get("groups") or []:
        views = [b for b in g["buttons"] if b["visible"]]
        print("  [%s] 共 %d 个，可见 %d 个" % (g["where"], g["count"], len(views)))
        for b in g["buttons"]:
            print("    %s %-12s id=%-16s class=%s"
                  % ("√" if b["visible"] else "×",
                     b["text"] or "(图标)", b["id"] or "-", b["cls"]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--url", default="http://127.0.0.1:18544/src/editor/editor.html")
    args = ap.parse_args(argv)

    client = CDPClient(port=args.port, timeout=30.0)
    if not client.is_alive():
        print("CDP 端口 %d 无响应" % args.port, file=sys.stderr)
        return 1
    client.ensure_page()
    client.send("Page.enable")
    client.send("Runtime.enable")
    client.navigate(args.url, timeout=30.0)
    ok = client.wait_for(
        "document.readyState==='complete' && !!document.getElementById('input')",
        timeout=20.0)
    if not ok:
        print("页面没就绪", file=sys.stderr)
        return 1

    for mode in ("small", "big"):
        show(run(client, mode))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
