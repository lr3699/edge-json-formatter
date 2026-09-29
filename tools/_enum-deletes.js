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
  function headingY(re) {
    var heads = deepAll('h1,h2,h3,h4,legend,label,.title,[class*=title]');
    var best = null;
    for (var i = 0; i < heads.length; i++) {
      var t = (heads[i].innerText || '').replace(/\s+/g, ' ').trim();
      if (re.test(t)) {
        var r = heads[i].getBoundingClientRect();
        if (r.width > 0 && (best === null || r.y < best)) best = Math.round(r.y);
      }
    }
    return best;
  }
  var dels = [];
  deepAll('button').forEach(function (b) {
    var lab = b.getAttribute('aria-label') || b.getAttribute('title') || '';
    if (/^delete$/i.test(lab.trim())) {
      var r = b.getBoundingClientRect();
      dels.push({ y: Math.round(r.y), x: Math.round(r.x), w: Math.round(r.width),
                  vis: r.width > 0, disp: getComputedStyle(b).display });
    }
  });
  dels.sort(function (a, b) { return a.y - b.y; });
  var logoY = headingY(/extension logo/i);
  var shotsY = headingY(/screenshot\/?s/i);
  var smallY = headingY(/small promotional/i);
  var largeY = headingY(/large promotional/i);
  return JSON.stringify({
    deleteButtons: dels,
    headings: { logo: logoY, shots: shotsY, small: smallY, large: largeY }
  }, null, 2);
})()
