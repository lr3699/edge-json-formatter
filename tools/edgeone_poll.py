# -*- coding: utf-8 -*-
"""轮询 EdgeOne Pages 部署状态，抓取分配的 edgeone.app 域名。"""
import re
import sys
import time

sys.path.insert(0, r"C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts")
from cdp import CDPClient  # noqa: E402


def main():
    c = CDPClient(host="127.0.0.1", port=9222, timeout=90)
    try:
        c.ensure_page(url_contains="console.cloud.tencent.com")
        c.send("Page.enable")
        domain = None
        for i in range(24):
            time.sleep(15)
            txt = c.evaluate(
                'document.body.innerText.replace(/\\s+/g, " ")'
            ).get("value") or ""
            m = re.search(r"[a-z0-9-]+\.edgeone\.app", txt)
            if m:
                domain = m.group(0)
            # 状态关键词
            status = "unknown"
            for kw, s in [
                ("部署成功", "DONE"), ("部署完成", "DONE"),
                ("构建中", "BUILDING"), ("部署中", "BUILDING"),
                ("排队中", "QUEUED"), ("部署失败", "FAILED"),
            ]:
                if kw in txt:
                    status = s
                    break
            print("attempt %d: status=%s domain=%s" % (i + 1, status, domain),
                  flush=True)
            if status == "DONE" and domain:
                print("DOMAIN:", domain)
                break
            if status == "FAILED":
                print("FAILED, head:", txt[:400])
                break
        else:
            print("TIMEOUT, last head:", txt[:400])
    finally:
        c.close()


if __name__ == "__main__":
    main()
