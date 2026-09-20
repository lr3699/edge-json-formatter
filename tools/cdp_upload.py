#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdp_upload.py —— 把本地文件注入页面的第 N 个 <input type="file">。

为什么不用 DOM.querySelector：
  1. 它**穿不透 shadow root**，Partner Center 的部分表单在 shadow DOM 里；
  2. 它只能取第一个匹配项，而 Partner Center 的 4 个上传位共用
     `input[name=fileuploader]`，必须按序号定位。

做法：先用 Runtime.evaluate 在页面里拿到目标元素对象（objectId），
再用 DOM.setFileInputFiles 传 objectId。既支持 shadow DOM，也支持序号。

用法：
    python cdp_upload.py --index 0 <文件…>
    python cdp_upload.py --list              # 列出页面上所有 file input
    python cdp_upload.py --list --deep       # 连 shadow DOM 里的一起列
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
    print("可用 CDP_SKILL_SCRIPTS 环境变量指定该目录。", file=sys.stderr)
    raise SystemExit(1)

# 在页面上下文里穿透 shadow root 收集元素的小工具
DEEP = (
    "function __deepAll(sel, root, acc){"
    "  root = root || document; acc = acc || [];"
    "  var hit; try { hit = root.querySelectorAll(sel); } catch(e){ hit = []; }"
    "  for (var i=0;i<hit.length;i++) acc.push(hit[i]);"
    "  var nodes = root.querySelectorAll('*');"
    "  for (var j=0;j<nodes.length;j++){"
    "    if (nodes[j].shadowRoot) __deepAll(sel, nodes[j].shadowRoot, acc);"
    "  }"
    "  return acc;"
    "}"
)


def _finder(selector, deep):
    """生成在页面里取元素列表的 JS 片段。"""
    sel = json.dumps(selector)
    if deep:
        return "__deepAll(%s)" % sel
    return "document.querySelectorAll(%s)" % sel


def list_file_inputs(client, deep=False):
    expr = (
        "(function(){ " + DEEP +
        "  var els = " + _finder("input[type=file]", deep) + ";"
        "  return Array.prototype.slice.call(els).map(function(el, i){"
        "    var r = el.getBoundingClientRect();"
        "    return { index:i, id:el.id||'', name:el.name||'', accept:el.accept||'',"
        "             multiple:!!el.multiple, disabled:!!el.disabled,"
        "             size:[Math.round(r.width),Math.round(r.height)],"
        "             inDocument: el.getRootNode()===document };"
        "  });"
        "})()"
    )
    return client.evaluate(expr).get("value") or []


def resolve_object(client, selector, index, deep, js=None):
    """返回目标元素的 objectId。

    js 优先：给的是一段「返回元素」的表达式，用于页面上多个 file input
    共用同一选择器、只能靠所在区块区分的场景。
    """
    if js:
        expr = "(%s)" % js
    else:
        expr = (
            "(function(){ " + DEEP +
            "  var els = " + _finder(selector, deep) + ";"
            "  return els[%d] || null;" % index +
            "})()"
        )
    res = client.send("Runtime.evaluate", {
        "expression": expr,
        "returnByValue": False,   # 关键：要 objectId
    })
    if res.get("exceptionDetails"):
        raise CDPError("求值异常：%s" % res["exceptionDetails"].get("text"))
    obj = (res.get("result") or {}).get("objectId")
    if not obj:
        raise CDPError("没定位到目标 file input（selector=%r index=%d js=%s）。"
                       % (selector, index, (js or '')[:60]))
    return obj


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    p = argparse.ArgumentParser(prog="cdp_upload.py", description="向页面第 N 个 file input 注入本地文件")
    p.add_argument("files", nargs="*", help="要上传的本地文件路径")
    p.add_argument("--selector", default="input[type=file]", help="CSS 选择器（默认 input[type=file]）")
    p.add_argument("--index", type=int, default=0, help="取第几个匹配项（默认 0）")
    p.add_argument("--js", help="自定义表达式：返回目标元素（优先于 selector/index）")
    p.add_argument("--js-file", help="从文件读取自定义表达式（避免命令行引号地狱）")
    p.add_argument("--deep", action="store_true", help="穿透 shadow DOM 查找")
    p.add_argument("--list", action="store_true", help="只列出页面上的 file input")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--target", help="指定标签页 targetId")
    p.add_argument("--url-contains", help="按 URL 关键字挑选标签页")
    p.add_argument("--timeout", type=float, default=30.0)
    args = p.parse_args(argv)

    client = CDPClient(host=args.host, port=args.port, timeout=args.timeout)
    try:
        if not client.is_alive():
            print("CDP_UNREACHABLE: %s 无响应" % client.base_http)
            return 2
        client.ensure_page(target=args.target, url_contains=args.url_contains)

        if args.list or not args.files:
            print(json.dumps(list_file_inputs(client, args.deep), ensure_ascii=False, indent=2))
            return 0

        missing = [f for f in args.files if not Path(f).exists()]
        if missing:
            print("错误：以下文件不存在：%s" % "、".join(missing), file=sys.stderr)
            return 1
        abs_files = [str(Path(f).resolve()) for f in args.files]

        client.send("DOM.enable")
        js = args.js
        if args.js_file:
            js = Path(args.js_file).read_text(encoding="utf-8").strip()
        obj = resolve_object(client, args.selector, args.index, args.deep, js)
        client.send("DOM.setFileInputFiles", {"files": abs_files, "objectId": obj})

        # 回读校验：浏览器会把选中的文件反映到 el.files。
        # 注意：Angular/React 上传成功后常会重建 <input>，此处可能读回空数组，
        # 属于「假阴性」，务必再用截图确认缩略图是否出现。
        check = (
            "(function(){ " + DEEP +
            "  var els = " + _finder(args.selector, args.deep) + ";"
            "  var el = els[%d];" % args.index +
            "  return el ? Array.prototype.map.call(el.files||[], function(f){return f.name;}) : null;"
            "})()"
        )
        got = client.evaluate(check).get("value") or []

        print(json.dumps({"selector": args.selector, "index": args.index,
                          "sent": abs_files, "detected": got,
                          "ok": len(got) == len(abs_files)},
                         ensure_ascii=False, indent=2))
        return 0
    except CDPError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
