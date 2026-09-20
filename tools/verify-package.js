/**
 * 上传前的包体检：node tools/verify-package.js [zip路径]
 *
 * 检查项：
 *   - zip 条目名使用正斜杠（ZIP 规范，严格校验器会因此报错）
 *   - manifest.json 位于包根目录
 *   - manifest 引用的图标文件都在包里
 *   - 商店字段长度限制（名称 ≤ 45 字符，描述 ≤ 132 字符）
 *   - 权限/主机权限清单打印出来，便于逐项撰写说明
 *   - 无 sourcemap / 临时文件 / 旧产物混入
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const zipMod = require('./zip.js');

const ROOT = path.resolve(__dirname, '..');
const zipPath = process.argv[2] ||
  path.join(ROOT, 'dist', 'json-formatter-pro-' + JSON.parse(
    fs.readFileSync(path.join(ROOT, 'manifest.json'), 'utf8')).version + '.zip');

let errors = 0;
let warnings = 0;

function ok(msg) { console.log('  \u2713 ' + msg); }
function bad(msg) { errors++; console.log('  \u2717 ' + msg); }
function warn(msg) { warnings++; console.log('  ! ' + msg); }

/** 从 zip 中取出单个条目的内容 */
function readEntry(buf, wantName) {
  let p = buf.length - 22;
  while (p >= 0 && buf.readUInt32LE(p) !== 0x06054b50) p--;
  let off = buf.readUInt32LE(p + 16);
  const count = buf.readUInt16LE(p + 10);
  for (let i = 0; i < count; i++) {
    if (buf.readUInt32LE(off) !== 0x02014b50) break;
    const method = buf.readUInt16LE(off + 10);
    const compSize = buf.readUInt32LE(off + 20);
    const nl = buf.readUInt16LE(off + 28);
    const el = buf.readUInt16LE(off + 30);
    const cl = buf.readUInt16LE(off + 32);
    const localOff = buf.readUInt32LE(off + 42);
    const name = buf.toString('utf8', off + 46, off + 46 + nl);
    if (name === wantName) {
      const lnl = buf.readUInt16LE(localOff + 26);
      const lel = buf.readUInt16LE(localOff + 28);
      const start = localOff + 30 + lnl + lel;
      const data = buf.slice(start, start + compSize);
      return method === 8 ? zlib.inflateRawSync(data) : data;
    }
    off += 46 + nl + el + cl;
  }
  return null;
}

console.log('体检包: ' + path.relative(ROOT, zipPath) + '\n');

if (!fs.existsSync(zipPath)) {
  bad('找不到压缩包：' + zipPath);
  process.exit(1);
}

const buf = fs.readFileSync(zipPath);
const names = zipMod.readZipNames(zipPath);

console.log('包结构');

const backslash = names.filter((n) => n.indexOf('\\') !== -1);
if (backslash.length) bad('条目名含反斜杠（不符合 ZIP 规范）：' + backslash.join(', '));
else ok('条目名全部使用正斜杠');

if (names.indexOf('manifest.json') === 0) ok('manifest.json 位于包根目录');
else if (names.includes('manifest.json')) ok('包含 manifest.json');
else bad('缺少 manifest.json');

const junkPatterns = [/\.map$/, /\.log$/, /~$/, /\.DS_Store$/i, /Thumbs\.db$/i,
  /^tools\//, /^docs\//, /^preview\//, /^dist\//, /^\./];
const junk = names.filter((n) => junkPatterns.some((r) => r.test(n)));
if (junk.length) bad('混入了不应打包的条目：' + junk.join(', '));
else ok('无 sourcemap / 日志 / 临时文件 / 开发目录');

console.log('\nmanifest 校验');

const manifestRaw = readEntry(buf, 'manifest.json');
if (!manifestRaw) {
  bad('无法读取 manifest.json');
  process.exit(1);
}
let manifest;
try {
  manifest = JSON.parse(manifestRaw.toString('utf8'));
  ok('manifest.json 是合法 JSON');
} catch (e) {
  bad('manifest.json 解析失败：' + e.message);
  process.exit(1);
}

if (manifest.manifest_version === 3) ok('使用 Manifest V3');
else bad('manifest_version 应为 3，实际为 ' + manifest.manifest_version);

if (!/^\d+(\.\d+){0,3}$/.test(manifest.version)) bad('version 格式不合法：' + manifest.version);
else ok('version = ' + manifest.version);

const name = manifest.name || '';
if (name.length > 45) bad('name 超过 45 字符（' + name.length + '）');
else ok('name 长度 ' + name.length + ' ≤ 45');

const desc = manifest.description || '';
if (!desc) bad('缺少 description');
else if (desc.length > 132) bad('description 超过 132 字符（' + desc.length + '）');
else ok('description 长度 ' + desc.length + ' ≤ 132');

if (manifest.icons) {
  let miss = 0;
  for (const k of Object.keys(manifest.icons)) {
    if (!names.includes(manifest.icons[k])) { bad('图标缺失：' + manifest.icons[k]); miss++; }
  }
  if (!miss) ok('manifest.icons 引用的 ' + Object.keys(manifest.icons).length + ' 个图标都在包里');
  if (!manifest.icons['128']) warn('建议提供 128x128 图标');
}

if (manifest.content_scripts && manifest.content_scripts.length) {
  const cs = manifest.content_scripts[0];
  let miss = 0;
  (cs.js || []).forEach((f) => { if (!names.includes(f)) { bad('内容脚本缺失：' + f); miss++; } });
  (cs.css || []).forEach((f) => { if (!names.includes(f)) { bad('内容脚本样式缺失：' + f); miss++; } });
  if (!miss) ok('内容脚本引用的文件都在包里');
}

if (manifest.background && manifest.background.service_worker) {
  if (!names.includes(manifest.background.service_worker)) {
    bad('service worker 缺失：' + manifest.background.service_worker);
  } else {
    ok('service worker 存在');
  }
}

if (manifest.options_ui || manifest.options_page) {
  const page = (manifest.options_ui && manifest.options_ui.page) || manifest.options_page;
  if (!names.includes(page)) bad('设置页缺失：' + page);
  else ok('设置页存在');
}

console.log('\n权限清单（提交时需逐项说明用途）');
console.log('  permissions      : ' + JSON.stringify(manifest.permissions || []));
console.log('  optional         : ' + JSON.stringify(manifest.optional_permissions || []));
console.log('  host_permissions : ' + JSON.stringify(manifest.host_permissions || []));

console.log('\n统计');
console.log('  条目数 : ' + names.length);
console.log('  体积   : ' + (buf.length / 1024).toFixed(1) + ' KB');
names.forEach((n) => console.log('    ' + n));

console.log('\n' + (errors ? errors + ' 项错误, ' : '') + warnings + ' 项提醒, ' +
  (errors ? '未通过' : '通过'));
process.exit(errors ? 1 : 0);
