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
  var all = deepAll('*');
  var out = [];
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    var t = (el.innerText || '').trim();
    if (t === 'Edit details' || t === 'Remove') {
      var r = el.getBoundingClientRect();
      out.push({
        text: t,
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute && el.getAttribute('role'),
        cls: (typeof el.className === 'string' ? el.className : '').slice(0, 70),
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
        kids: el.children.length,
        vis: r.width > 0 && r.height > 0
      });
    }
  }
  // 同时看看表格行结构，确认语言行数
  var rows = [];
  deepAll('*', null, []).forEach(function (el) {
    if (/^(TR|v6_he-table-row)$/i.test(el.tagName)) {
      var t = (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80);
      if (t) rows.push({ tag: el.tagName.toLowerCase(), text: t });
    }
  });
  return JSON.stringify({ url: location.href, actions: out, rows: rows.slice(0, 12) }, null, 2);
})()
