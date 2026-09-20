/**
 * 本地静态预览服务（零依赖）。
 *
 *   node tools/serve.js [端口] [根目录]
 *
 * 默认端口 18544，默认根目录为项目根。用来在浏览器里直接打开
 * preview/demo.html 预览查看器效果，或配合 tools/test-server.js 做假接口调试。
 */
'use strict';

const fs = require('fs');
const http = require('http');
const path = require('path');

const port = parseInt(process.argv[2] || '18544', 10);
const root = path.resolve(process.argv[3] || path.join(__dirname, '..'));

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.htm': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/plain; charset=utf-8',
  '.woff2': 'font/woff2'
};

const INDEX = [
  ['src/editor/editor.html', '粘贴 JSON 格式化（独立编辑页，可交互）'],
  ['preview/demo.html', '查看器效果预览（可交互）'],
  ['preview/demo.html?theme=dark', '同一页面的深色主题'],
  ['preview/demo.html?q=Status', '搜索定位演示'],
  ['preview/demo.html?depth=1', '只展开一层'],
  ['preview/demo.html?line=1', '带行号'],
  ['src/popup/popup.html', '工具栏弹窗（静态）'],
  ['src/options/options.html', '设置页（静态）']
];

function send(res, code, type, body) {
  res.writeHead(code, {
    'Content-Type': type,
    'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*'
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  let urlPath;
  try {
    urlPath = decodeURIComponent(req.url.split('?')[0]);
  } catch (e) {
    send(res, 400, 'text/plain; charset=utf-8', 'bad request');
    return;
  }

  if (urlPath === '/' || urlPath === '') {
    const items = INDEX.map(([href, label]) =>
      '<li><a href="/' + href + '">' + label + '</a> <code>/' + href + '</code></li>'
    ).join('');
    send(res, 200, MIME['.html'],
      '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">' +
      '<title>JSON 格式化查看器 · 本地预览</title><style>' +
      'body{margin:0;padding:32px 24px;font:14px/1.7 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;' +
      'background:#f7f8fa;color:#333}.w{max-width:760px;margin:0 auto}h1{font-size:19px;margin:0 0 6px}' +
      'p{color:#9aa0a6;margin:0 0 20px;font-size:13px}.card{background:#fff;border:1px solid #e8e8e8;' +
      'border-radius:12px;padding:8px 20px}ul{list-style:none;padding:0;margin:0}li{padding:11px 0;' +
      'border-top:1px solid #f0f0f0;display:flex;justify-content:space-between;gap:16px;align-items:baseline}' +
      'li:first-child{border-top:0}a{color:#3ab54a;text-decoration:none;font-weight:600}a:hover{text-decoration:underline}' +
      'code{color:#92278f;background:rgba(146,39,143,.08);padding:2px 7px;border-radius:5px;font-size:12px}' +
      '</style></head><body><div class="w"><h1>JSON 格式化查看器 · 本地预览</h1>' +
      '<p>以下页面直接复用扩展里的查看器代码，无需安装扩展。</p>' +
      '<div class="card"><ul>' + items + '</ul></div></div></body></html>');
    return;
  }

  const target = path.join(root, urlPath);
  if (!target.startsWith(root)) {
    send(res, 403, 'text/plain; charset=utf-8', 'forbidden');
    return;
  }

  fs.stat(target, (err, st) => {
    if (err || !st.isFile()) {
      send(res, 404, 'text/plain; charset=utf-8', 'not found: ' + urlPath);
      return;
    }
    const type = MIME[path.extname(target).toLowerCase()] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': type, 'Cache-Control': 'no-store' });
    fs.createReadStream(target).pipe(res);
  });
});

server.listen(port, '127.0.0.1', () => {
  console.log('预览服务已启动');
  console.log('  首页      : http://127.0.0.1:' + port + '/');
  console.log('  粘贴格式化 : http://127.0.0.1:' + port + '/src/editor/editor.html');
  console.log('  查看器预览 : http://127.0.0.1:' + port + '/preview/demo.html');
  console.log('  深色主题   : http://127.0.0.1:' + port + '/preview/demo.html?theme=dark');
  console.log('  根目录     : ' + root);
});
