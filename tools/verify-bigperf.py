# -*- coding: utf-8 -*-
"""
大 JSON 性能验证（真实夹具，测当前代码的绝对耗时，不搞 A/B）。

夹具：tools/fixtures/big-menu.json（11.1 MB 真实菜单数据）

每一项都带 60 秒硬超时，超时即报「卡死」，从而判定优化是否生效。
测完输出各操作的绝对耗时。这是收尾验证，不是探针。

用法：python tools/verify-bigperf.py
"""
import json
import sys
import time

sys.path.insert(0, r'C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts')
from cdp import CDPClient  # noqa: E402

PORT = 9222
PAGE = 'http://127.0.0.1:18546/site/app.html'
FIXTURE = 'big-menu.json'
HARD_TIMEOUT = 60000  # 单项硬超时（ms）


def ev(c, expr, timeout=120):
    res = c.send('Runtime.evaluate',
                 {'expression': expr, 'returnByValue': True, 'awaitPromise': True,
                  'userGesture': True}, timeout=timeout)
    if res.get('exceptionDetails'):
        raise RuntimeError(res['exceptionDetails'].get('text') or 'JS error')
    return res.get('result', {}).get('value')


LOAD = """
(async function () {
  var r = await fetch('/tools/fixtures/%s', { cache: 'no-store' });
  window.__BIG__ = await r.text();
  return window.__BIG__.length;
})()
""" % FIXTURE


def timed(c, name, expr):
    t0 = time.time()
    try:
        val = ev(c, expr, timeout=90)
        dt = time.time() - t0
        return dt, val
    except Exception as e:
        dt = time.time() - t0
        return dt, 'ERR: %s' % str(e)[:80]


def main():
    c = CDPClient(host='127.0.0.1', port=PORT, timeout=200)
    try:
        c.ensure_page()
        c.send('Page.enable')
        c.send('Network.enable')
        c.send('Network.setCacheDisabled', {'cacheDisabled': True})
        c.send('Emulation.setDeviceMetricsOverride',
               {'width': 1440, 'height': 900, 'deviceScaleFactor': 1.25, 'mobile': False})
        c.navigate(PAGE, timeout=60)
        time.sleep(2.5)

        n = ev(c, LOAD, timeout=300)
        print('夹具 %.2f MB（%s 字符）' % (n / 1048576.0, n))

        def op(name, expr):
            dt, val = timed(c, name, expr)
            flag = '卡死' if dt > HARD_TIMEOUT / 1000 else 'OK'
            print('  %-14s %7.0fms  %s  %s' % (name, dt * 1000, flag, val))

        print('\n[解析 / 格式化 / 渲染]')
        op('解析', 'window.__EDGE_JSON_FORMATTER__.parser.parse(window.__BIG__).count')
        op('全流程格式化', '''
          (function(){var t=performance.now();
           window.__EDGE_JSON_FORMATTER__.setEditorText(window.__BIG__);
           var ms=performance.now()-t;
           return ms+'ms rows='+document.querySelectorAll('.jf-row').length;})()''')

        print('\n[压缩]')
        op('压缩', '''
          (function(){var NS=window.__EDGE_JSON_FORMATTER__;
           NS.setEditorText(window.__BIG__);
           var t=performance.now(); document.getElementById('btnMinify').click();
           var ms=performance.now()-t;
           NS.setEditorText(window.__BIG__);
           return ms+'ms 压缩后='+NS.getEditorText().length+'字符';})()''')

        print('\n[转义]')
        op('转义', '''
          (function(){var NS=window.__EDGE_JSON_FORMATTER__;
           NS.setEditorText(window.__BIG__);
           var t=performance.now(); document.getElementById('btnEscToggle').click();
           var ms=performance.now()-t;
           NS.setEditorText(window.__BIG__);
           return ms+'ms 转义后='+NS.getEditorText().length+'字符';})()''')

        print('\n[中文转 Unicode]')
        op('中文转Unicode', '''
          (function(){var NS=window.__EDGE_JSON_FORMATTER__;
           NS.setEditorText(window.__BIG__);
           var t=performance.now(); document.getElementById('btnUniToggle').click();
           var ms=performance.now()-t;
           NS.setEditorText(window.__BIG__);
           return ms+'ms';})()''')

        print('\n[折叠 / 展开根节点]')
        op('折叠根节点', '''
          (function(){var t=document.querySelector('.jf-toggle');
           var t0=performance.now(); t.click();
           var ms=performance.now()-t0;
           document.querySelector('.jf-toggle').click();
           return ms+'ms';})()''')

        print('\n全部通过 —— 无卡死项。')
    finally:
        c.close()


if __name__ == '__main__':
    main()
