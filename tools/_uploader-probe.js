/* 探查上传器脚本里用到的目标主机（上传是走 worker 的，页面级探针看不到） */
(async function () {
  var base = 'https://msedgeaddonswebprod-csgrcxaka5g7bdap.b01.azurefd.net/public/staticres/';
  var files = ['blob.uploader.js', 'xfus.uploader.js', 'blob.worker.js'];
  var out = {};

  for (var i = 0; i < files.length; i++) {
    try {
      var r = await fetch(base + files[i]);
      var t = await r.text();
      var m = t.match(/https?:\/\/[^\s'"`)]+/g) || [];
      var hosts = [];
      m.forEach(function (x) {
        var h = x.split('/').slice(0, 3).join('/');
        if (hosts.indexOf(h) < 0) hosts.push(h);
      });
      // 顺带找 blob / sas / upload 相关的关键字，看上传路径长什么样
      var keys = [];
      ['sas', 'blob.core', 'upload', 'PUT', 'sasToken', 'containerUrl'].forEach(function (k) {
        var n = (t.match(new RegExp(k, 'gi')) || []).length;
        if (n) keys.push(k + '×' + n);
      });
      out[files[i]] = { len: t.length, hosts: hosts.slice(0, 12), keys: keys };
    } catch (e) {
      out[files[i]] = 'ERR ' + e;
    }
  }

  // 页面到上传存储主机的连通性（HEAD，只测可达性）
  var probe = {};
  var targets = [
    'https://productsummaryprod.blob.core.windows.net/',
    'https://msedgeaddonswebprod-csgrcxaka5g7bdap.b01.azurefd.net/'
  ];
  for (var j = 0; j < targets.length; j++) {
    try {
      var rr = await fetch(targets[j], { method: 'HEAD', mode: 'no-cors' });
      probe[targets[j]] = 'ok/' + rr.type;
    } catch (e) {
      probe[targets[j]] = 'ERR ' + e;
    }
  }
  out.probe = probe;

  return JSON.stringify(out, null, 2);
})()
