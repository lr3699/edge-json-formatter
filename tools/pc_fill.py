#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pc_fill.py —— 用一份 JSON 计划批量填写 Partner Center 表单控件。

为什么要这个脚本：描述文本很长（上千字），塞进命令行 / JS 文件容易被
引号、换行、中文转义搞坏。改成「JSON 计划 + Python 生成 JS」，一次解决。

计划文件格式：
{
  "deep": true,                     // 是否穿透 shadow DOM（默认 true）
  "fields": [
    {"selector": "#formly_50_textarea_description_1", "value": "……"},
    {"selector": "input[type=file]", "index": 2, "value": "……"},
    {"selector": "input[type=checkbox]", "index": 3, "check": true}
  ]
}

用法：
    python pc_fill.py plan.json [--port 9222] [--url-contains listings]
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
    print("无法导入 cdp.py：%s" % exc, file=sys.stderr)
    raise SystemExit(1)

# 页面侧执行体：接收一个 plan 数组，逐个设置控件
RUNTIME = r"""
(function (plan, deep) {
  function deepQuery(sel, root, acc) {
    root = root || document; acc = acc || [];
    var hit; try { hit = root.querySelectorAll(sel); } catch (e) { hit = []; }
    for (var i = 0; i < hit.length; i++) acc.push(hit[i]);
    var nodes = root.querySelectorAll('*');
    for (var j = 0; j < nodes.length; j++) {
      if (nodes[j].shadowRoot) deepQuery(sel, nodes[j].shadowRoot, acc);
    }
    return acc;
  }
  function query(sel, deep) {
    if (deep) return deepQuery(sel);
    return Array.prototype.slice.call(document.querySelectorAll(sel));
  }
  function visualSort(els) {
    return els.slice().sort(function (a, b) {
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      if (Math.abs(ra.top - rb.top) < 6) return ra.left - rb.left;
      return ra.top - rb.top;
    });
  }
  function fire(el, evts) {
    evts.forEach(function (n) { el.dispatchEvent(new Event(n, { bubbles: true })); });
  }

  var results = [];
  plan.forEach(function (item) {
    var found = query(item.selector, deep !== false).filter(function (e) { return !e.disabled; });
    // 默认跳过「零尺寸」控件：表单里常混有隐藏的模板控件（都在 0,0），
    // 不排除会导致视觉序号整体偏移一位。
    if (item.allowHidden !== true) {
      found = found.filter(function (e) {
        var r = e.getBoundingClientRect();
        return r.width > 0 || r.height > 0;
      });
    }
    if (item.visual !== false) found = visualSort(found);
    var el = found[item.index || 0];
    if (!el) {
      results.push({ sel: item.selector, i: item.index || 0, ok: false,
                     reason: 'NOT_FOUND', n: found.length });
      return;
    }
    var tag = (el.tagName || '').toUpperCase();

    if (item.check !== undefined) {
      var want = item.check !== false;
      if (el.type === 'radio') {
        if (want && !el.checked) el.click();
      } else {
        if (el.checked !== want) el.click();
      }
      results.push({ sel: item.selector, i: item.index || 0, ok: true,
                     kind: 'check', checked: el.checked });
      return;
    }

    if (tag === 'SELECT') {
      var opt = Array.prototype.slice.call(el.options).filter(function (o) {
        return (o.textContent || '').trim() === String(item.value);
      })[0] || Array.prototype.slice.call(el.options).filter(function (o) {
        return o.value === String(item.value);
      })[0];
      if (!opt) {
        results.push({ sel: item.selector, ok: false, reason: 'OPTION_NOT_FOUND' });
        return;
      }
      el.value = opt.value;
      fire(el, ['input', 'change', 'blur']);
      results.push({ sel: item.selector, ok: true, kind: 'select', set: opt.value });
      return;
    }

    var proto = tag === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                   : window.HTMLInputElement.prototype;
    var desc = Object.getOwnPropertyDescriptor(proto, 'value');
    el.focus();
    if (desc && desc.set) desc.set.call(el, String(item.value));
    else el.value = String(item.value);
    fire(el, ['input', 'change', 'blur']);
    results.push({ sel: item.selector, i: item.index || 0, ok: true,
                   kind: tag.toLowerCase(), len: (el.value || '').length,
                   head: (el.value || '').slice(0, 30) });
  });

  return JSON.stringify({ ok: results.every(function (r) { return r.ok; }), results: results });
})
"""


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(prog="pc_fill.py", description="按 JSON 计划批量填写表单")
    p.add_argument("plan", help="计划 JSON 文件")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--url-contains", help="按 URL 关键字挑选标签页")
    p.add_argument("--timeout", type=float, default=30.0)
    args = p.parse_args(argv)

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    fields = plan.get("fields", plan if isinstance(plan, list) else [])
    deep = plan.get("deep", True)

    client = CDPClient(host=args.host, port=args.port, timeout=args.timeout)
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: %s 无响应" % client.base_http)
            return 2
        client.ensure_page(url_contains=args.url_contains)

        expr = "(%s)(%s, %s)" % (RUNTIME, json.dumps(fields, ensure_ascii=False),
                                 "true" if deep else "false")
        res = client.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "userGesture": True,
        }, timeout=args.timeout)
        if res.get("exceptionDetails"):
            exc = res["exceptionDetails"]
            print("JS 异常：%s" % ((exc.get("exception") or {}).get("description") or exc.get("text")),
                  file=sys.stderr)
            return 1
        raw = (res.get("result") or {}).get("value")
        print(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, indent=2))
        return 0
    except CDPError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
