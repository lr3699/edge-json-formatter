# -*- coding: utf-8 -*-
"""暗色主题 + 640px 复查截图。"""
import sys
import time

sys.path.insert(0, r"C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts")
from cdp import CDPClient  # noqa: E402

SHOTS = r"C:\Users\X\WorkBuddy\2026-09-20-11-24-33\edge-json-formatter\docs\shots"


def main():
    c = CDPClient(host="127.0.0.1", port=9222, timeout=90)
    try:
        c.ensure_page()
        c.send("Page.enable")
        c.navigate("http://127.0.0.1:18544/app.html", timeout=25)
        time.sleep(2.5)
        c.evaluate('document.documentElement.setAttribute("data-theme","dark")')
        time.sleep(0.5)
        c.send("Emulation.setDeviceMetricsOverride",
               {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.6)
        c.screenshot(SHOTS + r"\w1440-dark.png")
        print("dark 1440 ok")
        c.send("Emulation.setDeviceMetricsOverride",
               {"width": 640, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.6)
        c.screenshot(SHOTS + r"\w640-v2.png")
        print("640 v2 ok")
    finally:
        c.close()


if __name__ == "__main__":
    main()
