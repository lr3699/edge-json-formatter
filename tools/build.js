/**
 * 打包扩展：产出可直接上传商店的 zip 与可直接加载的干净目录。
 *
 *   node tools/build.js
 *
 * 只收录运行期必需的文件（manifest / src / icons / 说明文档），
 * 排除 tools、preview、docs、dist、各种临时目录与旧产物。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zip = require('./zip.js');

const ROOT = path.resolve(__dirname, '..');
const DIST = path.join(ROOT, 'dist');
const STAGE = path.join(DIST, 'unpacked');

const INCLUDE_FILES = ['manifest.json', 'README.md', 'PRIVACY.md', 'CHANGELOG.md'];
const INCLUDE_DIRS = ['src', 'icons'];
const EXCLUDE = new Set(['icons/store-icon-300.png']);

function rmrf(target) {
  if (!fs.existsSync(target)) return;
  fs.rmSync(target, { recursive: true, force: true });
}

function copyInto(rel, srcDir) {
  const src = path.join(ROOT, srcDir);
  for (const name of fs.readdirSync(src).sort()) {
    const from = path.join(src, name);
    const relPath = rel + '/' + name;
    const st = fs.statSync(from);
    if (st.isDirectory()) {
      copyInto(relPath, srcDir + '/' + name);
      continue;
    }
    if (EXCLUDE.has(relPath)) continue;
    const to = path.join(STAGE, relPath);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(from, to);
    console.log('  + ' + relPath);
  }
}

function main() {
  const manifestPath = path.join(ROOT, 'manifest.json');
  if (!fs.existsSync(manifestPath)) throw new Error('找不到 manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const version = manifest.version;
  const zipPath = path.join(DIST, 'json-formatter-pro-' + version + '.zip');

  console.log('打包 JSON 格式化查看器 v' + version + '\n');

  rmrf(STAGE);
  fs.mkdirSync(STAGE, { recursive: true });

  for (const f of INCLUDE_FILES) {
    const from = path.join(ROOT, f);
    if (!fs.existsSync(from)) continue;
    fs.copyFileSync(from, path.join(STAGE, f));
    console.log('  + ' + f);
  }
  for (const d of INCLUDE_DIRS) {
    if (!fs.existsSync(path.join(ROOT, d))) continue;
    copyInto(d, d);
  }

  // 校验 manifest 引用到的图标都在包里
  const iconGroups = [];
  if (manifest.icons) iconGroups.push(manifest.icons);
  if (manifest.action && manifest.action.default_icon) iconGroups.push(manifest.action.default_icon);
  for (const group of iconGroups) {
    for (const key of Object.keys(group)) {
      const file = path.join(STAGE, group[key]);
      if (!fs.existsSync(file)) throw new Error('manifest 引用的图标缺失：' + group[key]);
    }
  }

  // 校验包内没有多余目录
  const stray = fs.readdirSync(STAGE).filter(
    (n) => !INCLUDE_FILES.includes(n) && !INCLUDE_DIRS.includes(n)
  );
  if (stray.length) throw new Error('包里出现多余条目：' + stray.join(', '));

  rmrf(zipPath);
  fs.mkdirSync(DIST, { recursive: true });
  const names = zip.build(STAGE, zipPath);
  const size = (fs.statSync(zipPath).size / 1024).toFixed(1);

  console.log('\n完成');
  console.log('  上传包  : ' + path.relative(ROOT, zipPath) + '  (' + size + ' KB, ' + names.length + ' 个文件)');
  console.log('  加载目录: ' + path.relative(ROOT, STAGE));
  console.log('\n下一步：见 docs/SUBMISSION.md');
}

main();
