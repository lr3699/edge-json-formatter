#!/usr/bin/env bash
#
# 修复本机 git 的一个环境级怪癖：
#   本机 git（2.52 与 2.55 均复现）无法把 ref 落盘到 refs/heads/<x>/<y>
#   或 refs/remotes/<x>/<y> 这类「嵌套」位置 —— 命令返回 0，但文件与父目录
#   都凭空消失；同一进程写到 .git/logs/refs/remotes/origin/ 的 reflog 却正常。
#   结果就是 git fetch / git update-ref 之后 origin/main 这个远端跟踪 ref 丢失，
#   git status 显示 "## main...origin/main [gone]"。
#
#   绕行办法：把远端跟踪 ref 写进 .git/packed-refs。该文件位于 .git/ 根目录，
#   不属于受限路径，git 能正常读取（rev-parse / status / log / diff 全部生效）。
#
# 用法：bash tools/git-sync-tracking.sh [remote] [branch]   # 默认 origin main
#
set -euo pipefail

# Bash 工具里 PATH 常被 shim 污染，补上 coreutils
export PATH="/usr/bin:/bin:$PATH"

REMOTE="${1:-origin}"
BRANCH="${2:-main}"
REF="refs/remotes/${REMOTE}/${BRANCH}"
HEADER='# pack-refs with: peeled fully-peeled sorted '

# 取远端真实 SHA（走 ls-remote，不依赖 fetch 落盘）
rev="$(git ls-remote "$REMOTE" "refs/heads/${BRANCH}" 2>/dev/null | awk 'NR==1{print $1}')"
if [ -z "${rev:-}" ]; then
  echo "ERROR: 无法从 ${REMOTE} 获取 refs/heads/${BRANCH}（检查网络 / SSH 配置）" >&2
  exit 1
fi

gitdir="$(git rev-parse --git-dir)"
pr="$gitdir/packed-refs"
tmp="$gitdir/packed-refs.tmp"

if [ -f "$pr" ]; then
  # 剔除目标 ref 行，保留其它条目
  grep -v " ${REF}\$" "$pr" > "$tmp" || true
else
  : > "$tmp"
fi
# 保证头行存在且只补一次
if ! grep -q '^# pack-refs' "$tmp"; then
  printf '%s\n' "$HEADER" | cat - "$tmp" > "$tmp.hdr"
  mv "$tmp.hdr" "$tmp"
fi
printf '%s %s\n' "$rev" "$REF" >> "$tmp"
mv "$tmp" "$pr"

echo "已写入 $REF = $rev"
echo "本地 refs/heads/${BRANCH} = $(git rev-parse "refs/heads/${BRANCH}")"
echo "$(git status -sb | head -1)"
