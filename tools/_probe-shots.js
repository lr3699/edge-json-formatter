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
  function sectionOf(headText) {
    var heads = deepAll('h1,h2,h3,h4,legend,label,.title,[class*=title]');
    for (var i = 0; i < heads.length; i++) {
      var t = (heads[i].innerText || '').replace(/\s+/g, ' ').trim();
      if (new RegExp(headText, 'i').test(t)) return heads[i];
    }
    return null;
  }
  function controls(head, patterns) {
    var node = head, hops = 0, found = [];
    while (node && hops < 14) {
      node = node.parentElement; hops++;
      if (!node) break;
      var els = node.querySelectorAll('button, [role=button]');
      for (var k = 0; k < els.length; k++) {
        var el = els[k], r = el.getBoundingClientRect();
        if (r.width === 0) continue;
        var label = el.getAttribute('aria-label') || el.getAttribute('title') || (el.innerText || '').trim();
        if (!label) continue;
        var hitp = patterns.some(function (p) { return new RegExp(p, 'i').test(label); });
        if (hitp) found.push({ label: label, at: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] });
      }
      if (found.length >= 1 && hops > 3) break;
    }
    return found;
  }
  var sh = sectionOf('screenshot');
  if (!sh) return JSON.stringify({ ok: false, reason: 'NO_SCREENSHOT_HEADING' });
  var dels = controls(sh, ['^delete$', '删除', 'trash']);
  var mag = controls(sh, ['magnify']);
  // 统计缩略图：Sreenshot 区块内的 img 数量
  var node = sh, hops = 0, imgs = 0, inputs = 0;
  while (node && hops < 14) {
    node = node.parentElement; hops++;
    if (!node) break;
    var ii = node.querySelectorAll('img'), fi = node.querySelectorAll('input[type=file]');
    if (ii.length || fi.length) { imgs = ii.length; inputs = fi.length; break; }
  }
  return JSON.stringify({
    ok: true,
    deleteButtons: dels,
    magnifyButtons: mag.length,
    imgThumbs: imgs,
    fileInputs: inputs
  }, null, 2);
})()
