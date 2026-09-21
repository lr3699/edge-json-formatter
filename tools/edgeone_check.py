# -*- coding: utf-8 -*-
"""检查腾讯云登录态并导航到 EdgeOne Pages 控制台。"""
import sys
import time

sys.path.insert(0, r"C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts")
from cdp import CDPClient  # noqa: E402

SHOTS = r"C:\Users\X\WorkBuddy\2026-09-20-11-24-33\edge-json-formatter\docs\shots"
CONSOLE = "https://console.cloud.tencent.com/edgeone/pages"


def main():
    time.sleep(4)
    c = CDPClient(host="127.0.0.1", port=9222, timeout=90)
    try:
        c.ensure_page()
        c.send("Page.enable")
        c.navigate(CONSOLE, timeout=45)
        time.sleep(10)
        url = c.page_url()
        print("url:", url)
        txt = c.evaluate(
            'document.body.innerText.replace(/\\s+/g, " ")'
        ).get("value") or ""
        print("head:", txt[:400])
        # 登录态判断：跳到登录页则未登录
        if "cloud.tencent.com/login" in url or "登录" in txt[:200]:
            print("LOGIN_REQUIRED")
        c.send("Emulation.setDeviceMetricsOverride",
               {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.5)
        c.screenshot(SHOTS + r"\edgeone-console.png")
        print("shot ok")
    finally:
        c.close()


if __name__ == "__main__":
    main()
