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
  // 定位 Screenshot/s 标题
  var heads = deepAll('h1,h2,h3,h4,legend,label,.title,[class*=title]');
  var sh = null;
  for (var i = 0; i < heads.length; i++) {
    var t = (heads[i].innerText || '').replace(/\s+/g, ' ').trim();
    if (/screenshot\/?s/i.test(t)) { sh = heads[i]; break; }
  }
  if (!sh) return JSON.stringify({ ok: false, reason: 'NO_HEADING' });

  // 向上找包含缩略图的容器
  var node = sh, hops = 0, container = null;
  while (node && hops < 14) {
    node = node.parentElement; hops++;
    if (!node) break;
    if (node.querySelectorAll('img').length >= 3) { container = node; break; }
  }
  if (!container) return JSON.stringify({ ok: false, reason: 'NO_CONTAINER' });

  // dump 容器内的可点控件：一切有 class 且含 icon/delete/trash/remove 的元素，
  // 以及所有 button / i / svg / span[onclick]
  var out = [];
  var all = container.querySelectorAll('*');
  for (var k = 0; k < all.length; k++) {
    var el = all[k];
    var cls = (typeof el.className === 'string' ? el.className : '');
    var tag = el.tagName.toLowerCase();
    if (/icon|delete|trash|remove|close|action|hover|pencil|copy/i.test(cls) && tag !== 'img') {
      var r = el.getBoundingClientRect();
      out.push({
        tag: tag,
        cls: cls.slice(0, 70),
        aria: el.getAttribute('aria-label'),
        title: el.getAttribute('title'),
        txt: (el.innerText || '').trim().slice(0, 20),
        w: Math.round(r.width), h: Math.round(r.height),
        kids: el.children.length
      });
    }
  }
  // 去重并限制条数
  var seen = {}, uniq = [];
  out.forEach(function (o) {
    var key = o.tag + '|' + o.cls + '|' + o.aria;
    if (!seen[key]) { seen[key] = 1; uniq.push(o); }
  });
  return JSON.stringify({ ok: true, containerCls: (typeof container.className === 'string' ? container.className : '').slice(0, 80), controls: uniq.slice(0, 40) }, null, 2);
})()
