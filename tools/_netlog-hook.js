/* 装网络探针：记录失败的 fetch / xhr / sendBeacon，便于定位上传卡在哪一步 */
(function () {
  if (window.__netlog) return 'already';
  window.__netlog = [];
  function push(s) { try { window.__netlog.push(String(s).slice(0, 200)); } catch (e) {} }

  var of = window.fetch;
  if (of) {
    window.fetch = function () {
      var a = arguments;
      return of.apply(this, a).then(function (r) {
        if (!r.ok) push('fetch ' + r.status + ' ' + r.url);
        return r;
      }, function (e) {
        push('fetch ERR ' + (a[0] && a[0].url ? a[0].url : a[0]) + ' :: ' + e);
        throw e;
      });
    };
  }

  var oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__u = u; this.__m = m; return oo.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function () {
    var x = this;
    x.addEventListener('error', function () { push('xhr ERR ' + x.__m + ' ' + x.__u); });
    x.addEventListener('timeout', function () { push('xhr TIMEOUT ' + x.__m + ' ' + x.__u); });
    x.addEventListener('load', function () { if (x.status >= 400) push('xhr ' + x.status + ' ' + x.__m + ' ' + x.__u); });
    return os.apply(this, arguments);
  };

  if (navigator.sendBeacon) {
    var ob = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = function (u, d) {
      var ok = ob(u, d);
      push('beacon ' + (ok ? 'ok' : 'FAIL') + ' ' + u);
      return ok;
    };
  }

  window.addEventListener('unhandledrejection', function (e) { push('unhandled: ' + e.reason); });
  return 'installed';
})()
