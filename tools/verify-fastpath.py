#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-fastpath.py —— 大 JSON「原生解析 + 惰性树」快路径的端到端验证（真实浏览器）。

验证点：
  1) 同步段耗时（解析 + 首屏建行）——用户感知的「卡」；
  2) 行号连续无断档、哨兵正常、总行数受闸门控制；
  3) 「加载更多」可推进，且推进后行号仍连续；
  4) 压缩/美化切换（纯 CSS，不重建 DOM）与输出文本正确性；
  5) 复制出来的输出与原生序列化逐字节一致（compact / pretty 两条）；
  6) 渲染出来的值文本与源码原文一致（核对 raw 还原）。

用法：先起本地服务（repo 根，端口 18546），浏览器开 9222 调试端口，然后
  python tools/verify-fastpath.py [--fixture /tools/fixtures/big-20mb.json]
"""
import argparse
import sys
import time
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "browser-automation-cdp" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from cdp import CDPClient  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:18546/site/app.html')
    ap.add_argument('--port', type=int, default=9222)
    ap.add_argument('--fixture', default='/tools/fixtures/big-20mb.json')
    a = ap.parse_args()

    c = CDPClient(host='127.0.0.1', port=a.port, timeout=900)
    try:
        c.ensure_page()
        c.send('Page.enable')
        c.send('Network.enable')
        c.send('Network.setCacheDisabled', {'cacheDisabled': True})
        c.send('Emulation.setDeviceMetricsOverride',
               {'width': 1440, 'height': 900, 'deviceScaleFactor': 1.25, 'mobile': False})
        c.navigate('%s?v=%d' % (a.url, time.time()), timeout=60)
        time.sleep(2.5)

        def ev(e, timeout=900):
            r = c.send('Runtime.evaluate', {'expression': e, 'returnByValue': True,
                                            'awaitPromise': True, 'userGesture': True},
                       timeout=timeout)
            if r.get('exceptionDetails'):
                return 'ERR: ' + str(r['exceptionDetails'])[:400]
            return r.get('result', {}).get('value')

        # 装一个「复制」拦截器：把 viewer 的输出文本抓出来（不发系统剪贴板）
        ev("""(function(){
          window.__cap='';
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            writeText:function(t){ window.__cap=t; return Promise.resolve(); }
          }});
          window.__hash=function(s){var x=5381;for(var i=0;i<s.length;i++){x=((x<<5)+x+s.charCodeAt(i))|0;}return (x>>>0)+':'+s.length;};
          return 'ok';
        })()""")

        print('加载 %s …' % a.fixture)
        print('    页面: %s' % ev('location.href'))
        diag = ev('fetch("%s",{cache:"no-store"}).then(r=>r.text()).then(t=>JSON.stringify({'
                  'status:0, len:t.length, head:t.slice(0,120)}))' % a.fixture)
        print('    诊断: %s' % diag)
        n = ev('fetch("%s",{cache:"no-store"}).then(r=>r.text()).then(t=>{window.__B__=t;return t.length})'
               % a.fixture)
        print('  源文本 %s 字符' % n)

        ev('window.__EDGE_JSON_FORMATTER__.setEditorText(window.__B__)')   # 预热
        time.sleep(4)

        print('\n[1] 同步段（解析 + 首屏建行）')
        for i in (1, 2):
            r = ev('(function(){var t=performance.now();'
                   'window.__EDGE_JSON_FORMATTER__.setEditorText(window.__B__);'
                   'return (performance.now()-t).toFixed(0);})()')
            print('    第%d次: %sms' % (i, r))

        print('\n[2] 行号连续性（稳定后）')
        time.sleep(2.5)
        print('    ' + str(ev("""(function(){
          var rows=document.querySelectorAll('.jf-row'), prev=0, bad=0, cnt=0, blank=0;
          for(var i=0;i<rows.length;i++){
            var g=rows[i].querySelector('.jf-no'); if(!g) continue;
            if(g.classList.contains('jf-no-more')){ blank++; continue; }
            var v=parseInt(g.textContent,10);
            if(!isNaN(v)){ cnt++; if(v!==prev+1) bad++; prev=v; }
          }
          return JSON.stringify({行数:rows.length, 已编号:cnt, 编号断档:bad,
                                 哨兵:blank, 最后行号:prev,
                                 DOM节点:document.getElementsByTagName('*').length});
        })()""")))

        print('\n[3] 加载更多')
        print('    ' + str(ev("""(function(){
          var s=[].slice.call(document.querySelectorAll('.jf-summary'))
                  .filter(function(x){return x.textContent.indexOf('\u8fd8\u6709')===0;})[0];
          if(!s) return JSON.stringify({跳过:'没有哨兵'});
          var before=document.querySelectorAll('.jf-row').length;
          var t=performance.now(); s.click();
          return JSON.stringify({点击耗时ms:+(performance.now()-t).toFixed(1), 点击前行数:before});
        })()""")))
        time.sleep(1.5)
        print('    ' + str(ev("""(function(){
          var rows=document.querySelectorAll('.jf-row'), prev=0, bad=0, cnt=0;
          for(var i=0;i<rows.length;i++){
            var g=rows[i].querySelector('.jf-no');
            if(!g || g.classList.contains('jf-no-more')) continue;
            var v=parseInt(g.textContent,10);
            if(!isNaN(v)){ cnt++; if(v!==prev+1) bad++; prev=v; }
          }
          return JSON.stringify({行数:rows.length, 已编号:cnt, 编号断档:bad, 最后行号:prev});
        })()""")))

        print('\n[3b] 折叠再展开：子元素不得重复追加（回归用例）')
        print('    ' + str(ev("""(function(){
          var toggles=[].slice.call(document.querySelectorAll('.jf-toggle'));
          var t=null, kids=null;
          for(var i=0;i<toggles.length;i++){
            var k=toggles[i].closest('.jf-row').nextElementSibling;
            if(k && k.classList.contains('jf-children') &&
               k.querySelectorAll('.jf-row').length>=3){ t=toggles[i]; kids=k; break; }
          }
          if(!t) return JSON.stringify({跳过:'找不到可折叠容器'});
          var n1=kids.querySelectorAll('.jf-row').length;
          t.click();                       // 折叠
          t.click();                       // 再展开
          var n2=kids.querySelectorAll('.jf-row').length;
          t.click(); t.click();            // 第二轮
          var n3=kids.querySelectorAll('.jf-row').length;
          // 行号也要保持连续
          var rows=kids.querySelectorAll('.jf-row'), prev=0, bad=0;
          for(var i=0;i<rows.length;i++){
            var g=rows[i].querySelector('.jf-no');
            if(!g || g.classList.contains('jf-no-more')) continue;
            var v=parseInt(g.textContent,10);
            if(!isNaN(v)){ if(v!==prev+1) bad++; prev=v; }
          }
          return JSON.stringify({首轮:n1, 一轮后:n2, 两轮后:n3,
                                 重复追加:(n2>n1||n3>n2), 行号断档:bad});
        })()""")))
        time.sleep(1.2)

        print('\n[3c] 后台续建未完成时就折叠/展开（flushFill 移除后的保护用例）')
        print('    ' + str(ev("""(function(){
          window.__EDGE_JSON_FORMATTER__.setEditorText(window.__B__);
          // 此刻分帧续建还没开始跑（setTimeout(0)），立即连点折叠/展开
          var toggles=[].slice.call(document.querySelectorAll('.jf-toggle'));
          var t=null, kids=null;
          for(var i=0;i<toggles.length;i++){
            var k=toggles[i].closest('.jf-row').nextElementSibling;
            if(k && k.classList.contains('jf-children') &&
               k.querySelectorAll('.jf-row').length>=3){ t=toggles[i]; kids=k; break; }
          }
          if(!t) return JSON.stringify({跳过:'找不到可折叠容器'});
          var n0=kids.querySelectorAll('.jf-row').length;
          t.click(); t.click(); t.click(); t.click();   // 折叠/展开两轮
          var n1=kids.querySelectorAll('.jf-row').length;
          return JSON.stringify({续建中行数:n0, 连点后行数:n1, 重复追加:n1>n0});
        })()""")))
        time.sleep(4)
        print('    ' + str(ev("""(function(){
          var rows=document.querySelectorAll('.jf-row'), prev=0, bad=0, cnt=0, blank=0;
          for(var i=0;i<rows.length;i++){
            var g=rows[i].querySelector('.jf-no');
            if(!g || g.classList.contains('jf-no-more')) continue;
            var v=parseInt(g.textContent,10);
            if(!isNaN(v)){ cnt++; if(v!==prev+1) bad++; prev=v; }
            else if(g.textContent==='') blank++;
          }
          return JSON.stringify({稳定后行数:rows.length, 已编号:cnt,
                                 编号断档:bad, 空行号:blank, 最后行号:prev});
        })()""")))

        print('\n[4] 压缩 / 美化切换（纯 CSS，DOM 不重建）')
        print('    ' + str(ev("""(function(){
          var btns=[].slice.call(document.querySelectorAll('.jf-btn'));
          var mode=btns.filter(function(b){var t=b.textContent.trim();
            return t==='\u538b\u7f29'||t==='\u7f8e\u5316';})[0];
          if(!mode) return 'ERR: 未找到压缩/美化按钮';
          var before=document.querySelectorAll('.jf-row').length;
          var t=performance.now(); mode.click();
          var t1=performance.now()-t;
          var after=document.querySelectorAll('.jf-row').length;
          return JSON.stringify({按钮文案:mode.textContent.trim(),
                                 切换耗时ms:+t1.toFixed(1),
                                 行数前:before, 行数后:after, 行数不变:before===after,
                                 body类:document.querySelector('.jf-body').className});
        })()""")))

        print('\n[5] 复制输出 vs 原生序列化')
        out = ev("""(function(){
          var btns=[].slice.call(document.querySelectorAll('.jf-btn'));
          var mode=btns.filter(function(b){var t=b.textContent.trim();
            return t==='\u538b\u7f29'||t==='\u7f8e\u5316';})[0];
          var copy=btns.filter(function(b){return b.textContent.indexOf('\u590d\u5236')>=0;})[0];
          if(!copy) return 'ERR: 未找到复制按钮';
          var nat=JSON.parse(window.__B__);
          var res={};
          function grab(){
            window.__cap='';
            copy.click();
            return window.__cap;
          }
          // 当前模式（应该是压缩）
          var compactText=grab();
          var compactRef=JSON.stringify(nat);
          res.compact = {实际:window.__hash(String(compactText)),
                         期望:window.__hash(compactRef),
                         一致:String(compactText)===compactRef};
          res.compactPreview=String(compactText).slice(0,60);
          mode.click();                         // 切回美化
          var prettyText=grab();
          var prettyRef=JSON.stringify(nat,null,'  ');
          res.pretty = {实际:window.__hash(String(prettyText)),
                        期望:window.__hash(prettyRef),
                        一致:String(prettyText)===prettyRef};
          res.prettyPreview=String(prettyText).slice(0,60);
          res.模式按钮文案=mode.textContent.trim();
          return JSON.stringify(res);
        })()""")
        print('    ' + str(out))

        print('\n[6] 渲染文本抽样核对（值展示用 raw，应与源码原文逐字一致）')
        print('    ' + str(ev("""(function(){
          var spans=document.querySelectorAll('.jf-str');
          var picked=[];
          for(var i=0;i<spans.length && picked.length<6;i++){
            if(spans[i].children.length) continue;
            var t=spans[i].textContent;
            if(t.length<6 || t.length>120) continue;
            picked.push(t);
          }
          var src=window.__B__;
          var hit=0;
          var detail=picked.map(function(t){
            var ok=src.indexOf(t)>=0; if(ok) hit++;
            return t.slice(0,36)+(ok?'  \u2713':"  \u2717 \u4e0d\u5728\u6e90\u6587\u4e2d");
          });
          return JSON.stringify({抽样:picked.length, 命中:hit, 明细:detail});
        })()""")))

        print('\n[7] 统计信息')
        print('    ' + str(ev("document.querySelector('.jf-status').textContent.trim()")))
    finally:
        c.close()


if __name__ == '__main__':
    main()
