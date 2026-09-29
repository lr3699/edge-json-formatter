(function () {
  function deepAll(sel, root, acc) {
    root = root || document; acc = acc || [];
    var hit; try { hit = root.querySelectorAll(sel); } catch (e) { hit = []; }
    for (var i = 0; i < hit.length; i++) acc.push(hit[i]);
    var nodes = root.querySelectorAll('*');
    for (var j = 0; j < nodes.length; j++) {
      if (nodes[j].shadowRoot) deepAll(sel, nodes[j].shadowRoot, acc);
    }
    return acc;
  }
  function nearestHeading(el) {
    // 向上找 6 层，取该层内部最近的标题文字
    var node = el, hops = 0;
    while (node && hops < 9) {
      node = node.parentElement;
      hops++;
      if (!node) break;
      var hs = node.querySelectorAll('h1,h2,h3,h4,legend,label,.title,[class*=title],[class*=heading]');
      for (var i = 0; i < hs.length; i++) {
        var t = (hs[i].innerText || '').replace(/\s+/g, ' ').trim();
        if (t && t.length < 70 && /logo|promotional|screenshot|tile|image/i.test(t)) {
          return t;
        }
      }
    }
    return null;
  }
  var ins = deepAll('input[type=file]');
  var out = [];
  for (var i = 0; i < ins.length; i++) {
    var el = ins[i];
    var p = el.parentElement, chain = [];
    for (var k = 0; k < 5 && p; k++) {
      chain.push(p.tagName.toLowerCase() + (typeof p.className === 'string' && p.className ? '.' + p.className.split(/\s+/).slice(0, 2).join('.') : ''));
      p = p.parentElement;
    }
    out.push({
      index: i,
      accept: el.getAttribute('accept'),
      multiple: el.multiple,
      heading: nearestHeading(el),
      parentChain: chain.join(' < ')
    });
  }
  // 抓所有可见的区块标题，用于交叉核对
  var titles = [];
  deepAll('h1,h2,h3,h4,legend,label').forEach(function (h) {
    var t = (h.innerText || '').replace(/\s+/g, ' ').trim();
    var r = h.getBoundingClientRect();
    if (t && t.length < 60 && r.width > 0) titles.push({ t: t, y: Math.round(r.y) });
  });
  return JSON.stringify({ inputs: out, visibleTitles: titles }, null, 2);
})()
