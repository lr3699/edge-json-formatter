"""渲染性能复测：11MB 真实样本。

验证三件事：
  1. 同步段耗时（解析 + 首屏建行）——用户感知的「卡」；
  2. 行号连续无断档（分帧补齐过程中行号也必须正确）；
  3. 渲染稳定后的行数确定、总量闸门（TOTAL_ROWS）生效。

用法：先起本地服务（repo 根），浏览器开 9222 调试端口，然后运行本脚本。
"""
from cdp import CDPClient

c = CDPClient(host='127.0.0.1', port=9222, timeout=300)
try:
    c.ensure_page()
    c.send('Page.enable'); c.send('Network.enable')
    c.send('Network.setCacheDisabled', {'cacheDisabled': True})
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': 1440, 'height': 900, 'deviceScaleFactor': 1.25, 'mobile': False})
    c.navigate('http://127.0.0.1:18546/site/app.html?v=%d' % time.time(), timeout=40)
    time.sleep(2.5)

    def ev(e, timeout=300):
        r = c.send('Runtime.evaluate', {'expression': e, 'returnByValue': True,
                                        'awaitPromise': True, 'userGesture': True}, timeout=timeout)
        if r.get('exceptionDetails'):
            return 'ERR: ' + str(r['exceptionDetails'])[:400]
        return r.get('result', {}).get('value')

    ev('fetch("/tools/fixtures/big-menu.json",{cache:"no-store"}).then(r=>r.text()).then(t=>{window.__B__=t;return t.length})')
    ev('window.__EDGE_JSON_FORMATTER__.setEditorText(window.__B__)')  # 预热
    time.sleep(3)

    for i in (1, 2):
        r = ev('(function(){var t=performance.now();'
               'window.__EDGE_JSON_FORMATTER__.setEditorText(window.__B__);'
               'return (performance.now()-t).toFixed(0);})()')
        print('第%d次 同步段（解析+首屏建行）: %sms' % (i, r))
        # 行号连续性 + 哨兵
        time.sleep(0.15)
        snap1 = ev('(function(){var n=document.querySelectorAll(".jf-row").length;'
                   'var s=[].slice.call(document.querySelectorAll(".jf-summary")).filter(function(x){return x.textContent.indexOf("\u8fd8\u6709")===0;}).length;'
                   'return JSON.stringify({rows:n,sentinel:s});})()')
        print('  150ms 后:', snap1)
        time.sleep(2.5)
        chk = ev("""(function(){
          var rows=document.querySelectorAll('.jf-row'), prev=0, bad=0, cnt=0, blank=0;
          for(var i=0;i<rows.length;i++){
            var g=rows[i].querySelector('.jf-no'); if(!g) continue;
            if(g.classList.contains('jf-no-more')){ blank++; continue; }
            var v=parseInt(g.textContent,10);
            if(!isNaN(v)){ cnt++; if(v!==prev+1) bad++; prev=v; }
          }
          return JSON.stringify({rows:rows.length, numbered:cnt, 编号断档:bad,
                                 哨兵:blank, 最后行号:prev});
        })()""")
        print('  稳定后:', chk)
        print('  节点总数:', ev('document.getElementsByTagName("*").length'))
        print()
finally:
    c.close()
