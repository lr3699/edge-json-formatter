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
  // 找 Extension logo 区块，再在该区块内找 aria-label=Delete 的按钮
  var heads = deepAll('h1,h2,h3,h4,legend,label,.title,[class*=title]');
  var logoHead = null;
  for (var i = 0; i < heads.length; i++) {
    var t = (heads[i].innerText || '').replace(/\s+/g, ' ').trim();
    if (/extension logo/i.test(t)) { logoHead = heads[i]; break; }
  }
  if (!logoHead) return JSON.stringify({ ok: false, reason: 'NO_LOGO_HEADING' });

  var node = logoHead, hops = 0, del = null;
  while (node && hops < 12 && !del) {
    node = node.parentElement; hops++;
    if (!node) break;
    var bs = node.querySelectorAll('button[aria-label=Delete], button[aria-label="Delete"]');
    for (var k = 0; k < bs.length; k++) {
      var r = bs[k].getBoundingClientRect();
      if (r.width > 0) { del = bs[k]; break; }
    }
  }
  if (!del) return JSON.stringify({ ok: false, reason: 'NO_DELETE_BTN' });
  var rect = del.getBoundingClientRect();
  del.click();
  return JSON.stringify({ ok: true, clicked: 'Delete', at: [Math.round(rect.x), Math.round(rect.y)] });
})()
