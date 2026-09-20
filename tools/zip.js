/**
 * 最小 ZIP 打包器（纯 Node，无依赖）。
 *
 * 存在的理由：Windows 上 .NET 的 ZipFile.CreateFromDirectory 会把条目名写成
 * 反斜杠（icons\icon16.png），不符合 ZIP 规范（必须用 /），部分严格校验器
 * （包括扩展商店的包校验）会因此报错。这里保证：
 *   - 路径分隔符统一为 /
 *   - 打开 UTF-8 名称标志位（bit 11），中文文件名不乱码
 *   - 固定时间戳，保证同样输入产出同样字节
 *
 * 用法：node tools/zip.js <源目录> <输出.zip>
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const DOS_TIME = 0x0000; // 1980-01-01 00:00:00
const DOS_DATE = 0x0021; // 1980-01-01

function crc32(buf) {
  let table = crc32.table;
  if (!table) {
    table = crc32.table = new Int32Array(256);
    for (let i = 0; i < 256; i++) {
      let c = i;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      table[i] = c;
    }
  }
  let crc = -1;
  for (let i = 0; i < buf.length; i++) {
    crc = (crc >>> 8) ^ table[(crc ^ buf[i]) & 0xff];
  }
  return (crc ^ -1) >>> 0;
}

function walk(dir, base, out) {
  for (const name of fs.readdirSync(dir).sort()) {
    const full = path.join(dir, name);
    const rel = base ? base + '/' + name : name;
    const st = fs.statSync(full);
    if (st.isDirectory()) walk(full, rel, out);
    else if (st.isFile()) out.push({ rel, full });
  }
}

function build(srcDir, zipPath) {
  const files = [];
  walk(srcDir, '', files);
  if (!files.length) throw new Error('源目录为空：' + srcDir);

  const localParts = [];
  const central = [];
  let offset = 0;

  for (const f of files) {
    const raw = fs.readFileSync(f.full);
    const crc = crc32(raw);
    const deflated = zlib.deflateRawSync(raw, { level: 9 });
    const useDeflate = deflated.length < raw.length;
    const data = useDeflate ? deflated : raw;
    const method = useDeflate ? 8 : 0;

    const nameBuf = Buffer.from(f.rel, 'utf8');
    if (nameBuf.length > 0xffff) throw new Error('路径过长：' + f.rel);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);              // version needed
    local.writeUInt16LE(0x0800, 6);          // UTF-8 name flag
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28);

    localParts.push(local, nameBuf, data);

    const cen = Buffer.alloc(46);
    cen.writeUInt32LE(0x02014b50, 0);
    cen.writeUInt16LE(20, 4);                // version made by
    cen.writeUInt16LE(20, 6);                // version needed
    cen.writeUInt16LE(0x0800, 8);            // UTF-8 name flag
    cen.writeUInt16LE(method, 10);
    cen.writeUInt16LE(DOS_TIME, 12);
    cen.writeUInt16LE(DOS_DATE, 14);
    cen.writeUInt32LE(crc, 16);
    cen.writeUInt32LE(data.length, 20);
    cen.writeUInt32LE(raw.length, 24);
    cen.writeUInt16LE(nameBuf.length, 28);
    cen.writeUInt16LE(0, 30);                // extra len
    cen.writeUInt16LE(0, 32);                // comment len
    cen.writeUInt16LE(0, 34);                // disk
    cen.writeUInt16LE(0, 36);                // internal attrs
    cen.writeUInt32LE(0, 38);                // external attrs
    cen.writeUInt32LE(offset, 42);
    central.push(cen, nameBuf);

    offset += local.length + nameBuf.length + data.length;
  }

  const centralBuf = Buffer.concat(central);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(files.length, 8);
  eocd.writeUInt16LE(files.length, 10);
  eocd.writeUInt32LE(centralBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  eocd.writeUInt16LE(0, 20);

  fs.writeFileSync(zipPath, Buffer.concat([Buffer.concat(localParts), centralBuf, eocd]));
  return files.map((f) => f.rel);
}

function readZipNames(zipPath) {
  const b = fs.readFileSync(zipPath);
  let p = b.length - 22;
  while (p >= 0 && b.readUInt32LE(p) !== 0x06054b50) p--;
  const n = b.readUInt16LE(p + 10);
  let off = b.readUInt32LE(p + 16);
  const names = [];
  for (let i = 0; i < n; i++) {
    if (b.readUInt32LE(off) !== 0x02014b50) break;
    const nl = b.readUInt16LE(off + 28);
    const el = b.readUInt16LE(off + 30);
    const cl = b.readUInt16LE(off + 32);
    names.push(b.toString('utf8', off + 46, off + 46 + nl));
    off += 46 + nl + el + cl;
  }
  return names;
}

if (require.main === module) {
  const [, , srcDir, zipPath] = process.argv;
  if (!srcDir || !zipPath) {
    console.error('用法: node tools/zip.js <源目录> <输出.zip>');
    process.exit(1);
  }
  const names = build(srcDir, zipPath);
  const size = fs.statSync(zipPath).size;
  console.log('打包完成: ' + zipPath + ' (' + (size / 1024).toFixed(1) + ' KB, ' + names.length + ' 个文件)');
  for (const n of names) console.log('  ' + n);
  const bad = readZipNames(zipPath).filter((n) => n.includes('\\'));
  if (bad.length) {
    console.error('错误：存在反斜杠路径 ' + bad.join(', '));
    process.exit(1);
  }
}

module.exports = { build, readZipNames };
