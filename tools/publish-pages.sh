#!/usr/bin/env bash
# 把 site/ 目录一键发布到 GitHub Pages
#
# 用法：
#   bash tools/publish-pages.sh <你的GitHub用户名> [仓库名]
#
# 例：
#   bash tools/publish-pages.sh xieliangrui
#   bash tools/publish-pages.sh xieliangrui json-privacy
#
# 首次运行时 git 会弹出浏览器/凭据管理器让你登录 GitHub，
# 按提示授权一次即可，后续无需再输入密码。

set -euo pipefail

GITHUB_USER="${1:-}"
REPO_NAME="${2:-json-formatter-pro}"

if [[ -z "$GITHUB_USER" ]]; then
  echo "用法: bash tools/publish-pages.sh <你的GitHub用户名> [仓库名]" >&2
  exit 1
fi

# 切到脚本所在项目的 site/ 目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_DIR="$(cd "$SCRIPT_DIR/../site" && pwd)"
cd "$SITE_DIR"

echo "==> 站点目录: $SITE_DIR"

# .nojekyll 必须存在，否则 GitHub Pages 会跳过下划线开头的文件
touch .nojekyll

if [[ ! -d .git ]]; then
  echo "==> 初始化 git 仓库"
  git init -b main >/dev/null
else
  echo "==> 已存在 git 仓库"
fi

git add -A

if git diff --cached --quiet && git rev-parse HEAD >/dev/null 2>&1; then
  echo "==> 没有新改动，跳过提交"
else
  git commit -m "Privacy policy site for Edge extension JSON Formatter Pro" >/dev/null
  echo "==> 已提交"
fi

REMOTE_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

echo "==> 推送到 $REMOTE_URL"
echo "    （若仓库还不存在，请先在 https://github.com/new 创建，名称填 $REPO_NAME，"
echo "      可见性选 Public，不要勾选任何初始化文件）"
echo

git push -u origin main

PAGES_ROOT="https://${GITHUB_USER}.github.io/${REPO_NAME}"

cat <<EOF

============================================================
推送完成。最后一步（只需做一次）：

  打开 https://github.com/${GITHUB_USER}/${REPO_NAME}/settings/pages
  Source 选择「Deploy from a branch」
  Branch 选 main ，目录选 / (root) ，点 Save

等 1~2 分钟后，商店要填的隐私政策 URL 就是：

  ${PAGES_ROOT}/privacy.html

功能介绍页（可选）：

  ${PAGES_ROOT}/
============================================================
EOF
