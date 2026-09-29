(function () {
  function deepAll(sel, root, acc) {
    root = root || document; acc = acc || [];
    var hit; try { hit = root.querySelectorAll(sel); } catch (e) { hit = []; }
    for (var i = 0; i < hit.length; i++) acc.push(hit[i]);
    var ns = root.querySelectorAll('*');
    for (var j = 0; j < ns.length; j++) {
      if (ns[j].shadowRoot) deepAll(sel, ns[j].shadowRoot, acc);
    }
    return acc;
  }
  // 找 Extension logo 区块
  var sections = deepAll('h1,h2,h3,h4,legend,label,.title,[class*=title]');
  var logoHead = null;
  for (var i = 0; i < sections.length; i++) {
    var t = (sections[i].innerText || '').replace(/\s+/g, ' ').trim();
    if (/extension logo/i.test(t)) { logoHead = sections[i]; break; }
  }
  if (!logoHead) return JSON.stringify({ ok: false, reason: 'NO_LOGO_HEADING' });

  var out = [];
  var node = logoHead, hops = 0;
  while (node && hops < 12) {
    node = node.parentElement; hops++;
    if (!node) break;
    // 找该层内的所有按钮 / 可点元素
    var els = node.querySelectorAll('button, a, [role=button], [aria-label], .fileuploader, input[type=file]');
    for (var k = 0; k < els.length; k++) {
      var el = els[k];
      var r = el.getBoundingClientRect();
      out.push({
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type'),
        aria: el.getAttribute('aria-label'),
        title: el.getAttribute('title'),
        cls: (typeof el.className === 'string' ? el.className : '').slice(0, 60),
        txt: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40),
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
        vis: r.width > 0 && r.height > 0
      });
    }
    if (out.length > 4) break;   // 已经进入包含控件的一层，够了
  }
  // 去重
  var seen = {}, uniq = [];
  out.forEach(function (o) {
    var key = o.tag + '|' + o.aria + '|' + o.txt + '|' + o.rect.join(',');
    if (!seen[key]) { seen[key] = 1; uniq.push(o); }
  });
  return JSON.stringify({ ok: true, heading: (logoHead.innerText || '').trim().slice(0, 40), els: uniq.slice(0, 25) }, null, 2);
})()
