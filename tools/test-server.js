/**
 * 端到端测试用的小型 HTTP 服务，模拟真实的 JSON 接口。
 *   node tools/test-server.js [port]
 *
 * 路由：
 *   /api/order    Content-Type: application/json   → 应被自动接管
 *   /api/plain    Content-Type: text/plain         → 依赖「纯文本自动格式化」开关
 *   /api/large    Content-Type: application/json   → 大响应
 *   /api/broken   Content-Type: application/json   → 非法 JSON，应显示错误卡片
 *   /api/html     Content-Type: text/html          → 普通网页，不应被接管
 */
const fs = require('fs');
const http = require('http');
const path = require('path');

const port = parseInt(process.argv[2] || '18543', 10);
const sample = fs.readFileSync(path.join(__dirname, 'sample.json'), 'utf8');

function bigJson(multiplier) {
  const base = JSON.parse(sample);
  const list = [];
  for (let i = 0; i < multiplier; i++) {
    for (const item of base.data.list) {
      list.push(Object.assign({}, item, { orderId: String(BigInt(item.orderId) + BigInt(i)) }));
    }
  }
  base.data.list = list;
  base.data.pageSize = list.length;
  return JSON.stringify(base);
}

const routes = {
  '/api/order': ['application/json', sample],
  '/api/plain': ['text/plain; charset=utf-8', sample],
  '/api/broken': ['application/json', '{\n  "code": "0",\n  "msg" "missing colon"\n}'],
  '/api/large': ['application/json', bigJson(1200)],
  '/api/html': ['text/html; charset=utf-8',
    '<!doctype html><html><head><meta charset="utf-8"><title>普通网页</title></head>' +
    '<body><h1>这是一个普通 HTML 页面</h1><p>内容里也有 {"a":1} 但不是 JSON 响应。</p></body></html>'],
};

routes['/'] = ['text/html; charset=utf-8',
  '<!doctype html><html><head><meta charset="utf-8"><title>测试导航</title></head><body>' +
  '<ul>' + Object.keys(routes).map((k) =>
    '<li><a href="' + k + '">' + k + '</a></li>').join('') +
  '</ul></body></html>'];

const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  const route = routes[url];
  if (!route) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('not found');
    return;
  }
  res.writeHead(200, { 'Content-Type': route[0], 'Cache-Control': 'no-store' });
  res.end(route[1]);
});

server.listen(port, '127.0.0.1', () => {
  console.log('test server listening on http://127.0.0.1:' + port);
  console.log('  order  : http://127.0.0.1:' + port + '/api/order');
  console.log('  plain  : http://127.0.0.1:' + port + '/api/plain');
  console.log('  broken : http://127.0.0.1:' + port + '/api/broken');
  console.log('  large  : http://127.0.0.1:' + port + '/api/large');
  console.log('  html   : http://127.0.0.1:' + port + '/api/html');
});
