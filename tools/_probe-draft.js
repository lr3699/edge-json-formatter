/* 读草稿详情 + 最近的上传相关请求，用于排查「Something went wrong」 */
(async function () {
  var m = /\/microsoftedge\/([0-9a-f-]{36})\//i.exec(location.pathname) ||
          /\/microsoftedge\/([0-9a-f-]{36})/i.exec(location.href);
  var PID = m ? m[1] : 'b5797b76-ba71-40f0-abd2-b1248f932cf1';
  var base = location.origin + '/en-us/dashboard/microsoftedge/api/' + PID;
  var out = { productId: PID, url: location.href };

  async function get(url) {
    try {
      var r = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' } });
      var t = await r.text();
      if (t.indexOf('<!DOCTYPE') === 0) return { status: r.status, body: null, note: 'HTML shell' };
      var b; try { b = JSON.parse(t); } catch (e) { b = t.slice(0, 300); }
      return { status: r.status, body: b };
    } catch (e) { return { status: 'ERR', body: String(e) }; }
  }

  out.draft = (await get(base + '/overview/submissiondetails/draftsubmission')).body;
  out.validity = (await get(base + '/submissionvalidity')).body;
  out.modules = (await get(base + '/FocusNav/modulestatus')).body;

  // 最近 30 条资源请求里，挑上传/包相关的
  var res = performance.getEntriesByType('resource') || [];
  out.pkgRequests = res
    .map(function (e) { return e.name; })
    .filter(function (n) { return /upload|blob|file|package|submission/i.test(n); })
    .slice(-25);

  return JSON.stringify(out, null, 2);
})()
