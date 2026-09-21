# -*- coding: utf-8 -*-
"""多宽度 + 亮暗主题截图顶部导航布局。"""
import sys
import time

sys.path.insert(0, r"C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts")
from cdp import CDPClient  # noqa: E402

SHOTS = r"C:\Users\X\WorkBuddy\2026-09-20-11-24-33\edge-json-formatter\docs\shots"

SIZES = [
    (1440, 900, "w1440"),
    (1100, 800, "w1100"),
    (860, 800, "w860"),
    (640, 800, "w640"),
    (480, 760, "w480"),
]


def main():
    c = CDPClient(host="127.0.0.1", port=9222, timeout=90)
    try:
        c.ensure_page()
        c.send("Page.enable")
        c.navigate("http://127.0.0.1:18544/app.html", timeout=25)
        time.sleep(2.5)
        for w, h, tag in SIZES:
            c.send("Emulation.setDeviceMetricsOverride",
                   {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
            time.sleep(0.6)
            c.screenshot(SHOTS + "\\" + tag + ".png")
            print(tag, "ok")
        # 亮色主题 1440
        c.send("Emulation.setDeviceMetricsOverride",
               {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        c.evaluate('document.documentElement.setAttribute("data-theme","light")')
        time.sleep(0.6)
        c.screenshot(SHOTS + r"\w1440-light.png")
        print("light ok")
    finally:
        c.close()


if __name__ == "__main__":
    main()
