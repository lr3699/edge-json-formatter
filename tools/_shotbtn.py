"""截按钮区（浅色 + 深色），确认边框配色效果。"""
import sys, time, base64, os
sys.path.insert(0, r'C:\Users\X\.workbuddy\skills\browser-automation-cdp\scripts')
from cdp import CDPClient

OUT = r'C:\Users\X\WorkBuddy\2026-09-20-11-24-33\edge-json-formatter\tools\_shot'
os.makedirs(OUT, exist_ok=True)
c = CDPClient(host='127.0.0.1', port=9222, timeout=300)
try:
    c.ensure_page()
    c.send('Page.enable'); c.send('Network.enable')
    c.send('Network.setCacheDisabled', {'cacheDisabled': True})
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': 1440, 'height': 900, 'deviceScaleFactor': 1.25, 'mobile': False})

    def ev(e):
        r = c.send('Runtime.evaluate', {'expression': e, 'returnByValue': True,
                                        'awaitPromise': True, 'userGesture': True})
        if r.get('exceptionDetails'):
            return 'ERR:' + str(r['exceptionDetails'])[:200]
        return r['result'].get('value')

    for theme in ('light', 'dark'):
        c.navigate('http://127.0.0.1:18546/site/app.html?v=%d' % time.time(), timeout=40)
        time.sleep(2.2)
        ev('NS=window.__EDGE_JSON_FORMATTER__;NS.applyEditorSettings({theme:"%s"});' % theme)
        time.sleep(0.5)
        clip = ev("""(function(){var p=document.querySelector('.panel-input header')||
                     document.querySelector('.panel-tools');if(!p)return null;
                     var r=p.getBoundingClientRect();
                     return {x:Math.max(0,Math.round(r.x-6)),y:Math.max(0,Math.round(r.y-6)),
                             width:Math.round(Math.min(760,r.width+12)),
                             height:Math.round(r.height+14),scale:1};})()""")
        params = {'format': 'png'}
        if clip:
            params['clip'] = clip
        shot = c.send('Page.captureScreenshot', params)['data']
        p = os.path.join(OUT, 'btns_%s.png' % theme)
        open(p, 'wb').write(base64.b64decode(shot))
        print(theme, '->', p)
finally:
    c.close()
