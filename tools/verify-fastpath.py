#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-fastpath.py —— 大 JSON「原生解析 + 惰性树」快路径的端到端验证（真实浏览器）。

验证点：
  0) 切到树视图：≥600KB 自动走全文视图，先点「树视图」按钮再验树上行为；
  1) 同步段耗时（解析 + 首屏建行）——用户感知的「卡」；
  2) 行号连续无断档、哨兵正常、总行数受闸门控制；
  3) 折叠 → 再展开：行表先减后完全还原（扁平行表架构；哨兵/「加载更多」
     随闸门续建一起退役，滚动连续性见 verify-virtual-tree.py）；
  4) 输出模式恒为美化（「压缩 / 美化」切换钮已按功能精简下线）；
  5) 复制出来的输出与原生美化序列化逐字节一致；
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

        # ≥600KB 的文档会自动走全文视图（bigview/CodeMirror），树上什么都没有 ——
        # 本测试验的是「原生快路径 + 惰性树 + 行号连续性」，所以先点全文工具条的
        # 「树视图」按钮把当前文档切回树视图（setBigMode(false)，与用户手动
        # 切换走同一条路；bigMode 是粘性的，后面重复 setEditorText 也留在树上）。
        print('\n[0] 切到树视图并全部展开（大文档默认走全文视图 + 只展开 3 层）')
        print('    ' + str(ev("""(function(){
          var btns=[].slice.call(document.querySelectorAll('#bigToolbar .jf-btn'));
          var tv=btns.filter(function(b){return b.textContent.trim()==='树视图';})[0];
          if(!tv) return JSON.stringify({错误:'找不到树视图按钮',
                                         按钮:btns.map(function(b){return b.textContent.trim();})});
          tv.click();
          return JSON.stringify({已点击:true});
        })()""")))
        tree_rows = 0
        for _ in range(80):                     # 最多等 20s 让树渲染出来
            time.sleep(0.25)
            tree_rows = ev("document.querySelectorAll('.jf-row').length")
            if tree_rows:
                break
        print('    树视图 DOM 行数：%s' % tree_rows)
        if not tree_rows:
            print('    [失败] 树视图没渲染出来，后续断言全部失去意义')
            return 4
        # 行号默认关闭（settings.lineNumbers=false），不开行号就验不了连续性
        ev("window.__EDGE_JSON_FORMATTER__.applyEditorSettings({lineNumbers:true})")
        # 大文档（>5 万节点）默认只展开前 3 层，行表只有几十行，没有哨兵、
        # 没有「加载更多」、也没有可折叠容器 —— 选「全部展开」把 36 万行
        # 的完整行表建出来，后续的行号连续性 / 哨兵 / 折叠回归才验得了。
        print('    ' + str(ev("""(function(){
          var sel=document.querySelector('.jf-level');
          if(!sel) return JSON.stringify({错误:'找不到层级下拉'});
          sel.value='all';
          sel.dispatchEvent(new Event('change',{bubbles:true}));
          return JSON.stringify({已选择:'all'});
        })()""")))
        total = 0
        for _ in range(120):                    # 最多等 30s 建完整行表
            time.sleep(0.25)
            total = ev("(document.querySelector('.jf-status')||{}).textContent"
                       ".match(/([\\d,]+)\\s*行/)")
            total = int(total[1].replace(',', '')) if total else 0
            if total > 100000:
                break
        print('    全部展开后行表长度：%s' % total)
        if total <= 100000:
            print('    [失败] 行表没建起来（%s），后续断言失去意义' % total)
            return 4

        print('\n[1] 同步段（解析 + 首屏建行）')
        for i in (1, 2):
            r = ev('(function(){var t=performance.now();'
                   'window.__EDGE_JSON_FORMATTER__.setEditorText(window.__B__);'
                   'return (performance.now()-t).toFixed(0);})()')
            print('    第%d次: %sms' % (i, r))

        print('\n[2] 行号连续性（稳定后）')
        time.sleep(2.5)
        print('    ' + str(ev("""(function(){
          var rows=document.querySelectorAll('.jf-row'), prev=0, bad=0, cnt=0;
          for(var i=0;i<rows.length;i++){
            var g=rows[i].querySelector('.jf-no'); if(!g) continue;
            var v=parseInt(g.textContent,10);
            if(!isNaN(v)){ cnt++; if(v!==prev+1) bad++; prev=v; }
          }
          return JSON.stringify({行数:rows.length, 已编号:cnt, 编号断档:bad,
                                 最后行号:prev,
                                 DOM节点:document.getElementsByTagName('*').length});
        })()""")))

        # [3] 哨兵 / 「加载更多」：老架构（闸门续建 + 嵌套 .jf-children DOM）
        # 的用例，虚拟化 + 惰性树重写后哨兵行已不存在 —— 滚动连续性与折叠
        # 回归由 verify-virtual-tree.py 第 2、3 节覆盖，这里只保留快路径
        # 视角下最有价值的一条：折叠让行表变短、再展开完全还原。

        print('\n[3b] 折叠 → 再展开：行表先减后完全还原（扁平行表架构）')
        print('    ' + str(ev("""(function(){
          function rows(){
            var m=(document.querySelector('.jf-status').textContent.match(/([\\d,]+)\\s*行/)||[])[1];
            return m?parseInt(m.replace(/,/g,''),10):-1;
          }
          var t=document.querySelector('.jf-window .jf-toggle');
          if(!t) return JSON.stringify({跳过:'找不到可折叠容器'});
          var n0=rows();
          t.click();                                    // 折叠第一个容器
          var n1=rows();
          var t2=document.querySelector('.jf-window .jf-toggle');
          if(t2) t2.click();                            // 再展开（同一行还在窗口里）
          var n2=rows();
          // 窗口内行号无重复（扁平行表下重复行号=行表重建 bug）
          var rs=[].slice.call(document.querySelectorAll('.jf-window .jf-row'));
          var seen={},dup=0;
          rs.forEach(function(r){var k=r.getAttribute('data-i');
            if(seen[k])dup++; seen[k]=1;});
          return JSON.stringify({折叠前:n0, 折叠后:n1, 再展开:n2,
                                 折叠有效:n1<n0, 完全还原:n2===n0, 窗口重复行:dup});
        })()""")))
        time.sleep(1.2)

        print('\n[4] 输出模式恒为美化（「压缩 / 美化」按钮已下线）')
        print('    ' + str(ev("""(function(){
          var btns=[].slice.call(document.querySelectorAll('.jf-toolbar .jf-btn'));
          var mode=btns.filter(function(b){var t=b.textContent.trim();
            return t==='压缩'||t==='美化';})[0];
          var rows=document.querySelectorAll('.jf-row').length;
          var body=document.querySelector('.jf-body');
          var compact=body?body.classList.contains('jf-compact'):null;
          var ctext=document.querySelector('.jf-ctext');
          return JSON.stringify({存在压缩美化按钮:!!mode, 压缩态:compact,
                                 紧凑文本:!!ctext, 树行数:rows, 行数正常:rows>0});
        })()""")))

        print('\n[5] 复制输出 vs 原生序列化（美化）')
        out = ev("""(function(){
          var btns=[].slice.call(document.querySelectorAll('.jf-btn'));
          var copy=btns.filter(function(b){return b.textContent.indexOf('复制')>=0;})[0];
          if(!copy) return 'ERR: 未找到复制按钮';
          var nat=JSON.parse(window.__B__);
          var res={};
          function grab(){
            window.__cap='';
            copy.click();
            return window.__cap;
          }
          var prettyText=grab();
          var prettyRef=JSON.stringify(nat,null,'  ');
          res.pretty = {实际:window.__hash(String(prettyText)),
                        期望:window.__hash(prettyRef),
                        一致:String(prettyText)===prettyRef};
          res.prettyPreview=String(prettyText).slice(0,60);
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
