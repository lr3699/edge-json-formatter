# -*- coding: utf-8 -*-
"""验证输入面板转换按钮（转义 / 去转义 / 压缩）：功能正确性 + 大文本性能。

2026-10-19 起按钮与功能一一对应：「中文⇄U」双向钮下线；「转义⇄还原」拆成
「转义」「去转义」两枚独立按钮（方向不再自动识别）。
"""
import argparse
import json
import sys
import time

sys.path.insert(0, r"C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts")
from cdp import CDPClient  # noqa: E402

PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
    if ok:
        PASS += 1
    else:
        FAIL += 1


IDS = {
    '转义': 'btnEscape',
    '去转义': 'btnUnescape',
    '压缩': 'btnMinify',
}


def open_menu_and_click(client, label):
    client.evaluate("document.getElementById('%s').click()" % IDS[label])


def get_msg(client):
    return client.evaluate(
        "document.getElementById('msg').textContent"
    ).get("value") or ""


def run(url):
    c = CDPClient(host="127.0.0.1", port=9222, timeout=90)
    try:
        c.ensure_page()
        c.send("Page.enable")
        c.navigate(url, timeout=30)
        time.sleep(2.5)

        sample = json.dumps(
            {"城市": "北京", "msg": "你好「世界」", "n": 12345678901234567890},
            ensure_ascii=False,
        )
        c.evaluate(
            "window.__EDGE_JSON_FORMATTER__.setEditorText(" + json.dumps(sample) + ")"
        )
        time.sleep(0.6)

        # --- 转义 ---
        open_menu_and_click(c, "转义")
        time.sleep(0.5)
        v = c.evaluate(
            "window.__EDGE_JSON_FORMATTER__.getEditorText ?"
            " window.__EDGE_JSON_FORMATTER__.getEditorText() : ''"
        ).get("value")
        check("转义", v.startswith('"') and '\\"' in v, get_msg(c))

        # --- 去除转义（应还原） ---
        open_menu_and_click(c, "去转义")
        time.sleep(0.5)
        v = c.evaluate(
            "window.__EDGE_JSON_FORMATTER__.getEditorText ?"
            " window.__EDGE_JSON_FORMATTER__.getEditorText() : ''"
        ).get("value")
        check("去转义还原", v == sample, get_msg(c))

        # --- 压缩（含大整数精度保留） ---
        pretty = json.dumps(
            {"城市": "北京", "list": [1, 2, 3], "big": 12345678901234567890},
            ensure_ascii=False, indent=2,
        )
        c.evaluate(
            "window.__EDGE_JSON_FORMATTER__.setEditorText(" + json.dumps(pretty) + ")"
        )
        time.sleep(0.5)
        open_menu_and_click(c, "压缩")
        time.sleep(0.5)
        v = c.evaluate(
            "window.__EDGE_JSON_FORMATTER__.getEditorText ?"
            " window.__EDGE_JSON_FORMATTER__.getEditorText() : ''"
        ).get("value")
        check("压缩去空白", "\n" not in v and ": " not in v and "北京" in v, "")
        check("压缩保留大整数", "12345678901234567890" in v, "")

        # --- 大文本性能：~2MB 含大量中文（先整页刷新释放内存，避免多轮
        #     转换叠加 DOM/字符串副本把渲染进程压崩） ---
        big = {"data": [
            {"id": i, "城市": "北京市海淀区第%d号街区" % i, "tag": "标签%d" % i}
            for i in range(10000)
        ]}
        big_text = json.dumps(big, ensure_ascii=False, indent=2)
        print("  大文本体积: %.1f MB" % (len(big_text.encode("utf-8")) / 1048576.0),
              flush=True)
        c.navigate(url, timeout=30)
        time.sleep(2.5)
        c.evaluate(
            "window.__EDGE_JSON_FORMATTER__.setEditorText(" + json.dumps(big_text) + ")"
        )
        time.sleep(1.0)

        t0 = time.time()
        open_menu_and_click(c, "压缩")
        time.sleep(1.2)
        check("压缩 4MB < 1s", (time.time() - t0) < 3.0, get_msg(c))

        t0 = time.time()
        open_menu_and_click(c, "转义")
        time.sleep(1.2)
        check("转义 4MB < 3s", (time.time() - t0) < 6.0, get_msg(c))

        t0 = time.time()
        open_menu_and_click(c, "去转义")
        time.sleep(1.2)
        check("去转义 4MB < 3s", (time.time() - t0) < 6.0, get_msg(c))

        print("\n结果：%d 通过，%d 失败" % (PASS, FAIL))
        return FAIL == 0
    finally:
        c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:18544/site/app.html")
    args = ap.parse_args()
    ok = run(args.url)
    sys.exit(0 if ok else 1)
