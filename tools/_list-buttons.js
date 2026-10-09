/* 列出页面上所有「按钮类」元素的可见文字（含 shadow DOM），用于确认该点哪个按钮 */
(function () {
  var out = [];
  function walk(root, depth) {
    if (depth > 16) return;
    var nodes = root.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var tag = (el.tagName || '').toLowerCase();
      var isBtn = tag === 'button' || tag === 'v6_he-button' ||
                  (el.getAttribute && el.getAttribute('role') === 'button');
      if (isBtn) {
        var t = (el.innerText || '').replace(/\s+/g, ' ').trim();
        if (t && t.length < 40) {
          var r = el.getBoundingClientRect();
          if (r.width > 0 && r.height > 0) {
            out.push(t + ' @[' + Math.round(r.left) + ',' + Math.round(r.top) + ']');
          }
        }
      }
      if (el.shadowRoot) walk(el.shadowRoot, depth + 1);
    }
  }
  walk(document, 0);
  var uniq = [];
  out.forEach(function (x) { if (uniq.indexOf(x) < 0) uniq.push(x); });
  return JSON.stringify(uniq);
})()
