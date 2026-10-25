#!/usr/bin/env bash
# sync_x_library_to_obsidian.sh — 把本机 X 参考库单向镜像到 Obsidian 的 _inbox/X/参考库
#
# 方向：本机 ~/x-reference 是唯一真源 → Obsidian 是只读镜像（--delete，源删了镜像也删）
# 不反向同步。想改内容改本机库，重跑本脚本即可。
#
# 产物：
#   ~/obsidian-vault/_inbox/X/参考库/{长文,短推,_仅摘要,索引.csv,索引.md,README.md}
# 然后只把该目录 add/commit/push，不碰 vault 里用户自己的笔记。
set -uo pipefail

SRC="${XRADAR_LIBRARY:-$HOME/x-reference}"
DST="${OBSIDIAN_SYNC_TARGET:-${OBSIDIAN_VAULT:-$HOME/obsidian-vault}/_inbox/X/参考库}"
VAULT="${OBSIDIAN_VAULT:-$HOME/obsidian-vault}"

[ -d "$SRC" ] || { echo "SKIP: 源目录不存在 $SRC"; exit 0; }
mkdir -p "$DST"

# 1) 单向镜像（_store.jsonl 是本机主库，体积大且无阅读价值，不进 Obsidian）
rsync -a --delete --exclude '_store.jsonl' "$SRC"/ "$DST"/
FILES=$(find "$DST" -type f | wc -l)
SIZE=$(du -sh "$DST" | cut -f1)
echo "镜像完成：$FILES 个文件 / $SIZE → $DST"

# 2) 只提交参考库目录
cd "$VAULT" || exit 0
if [ -d .git ]; then
  # vault 里常有用户自己没提交的笔记，直接 pull 会被拒绝；
  # --autostash 会把它们暂存、rebase 完再放回，不会丢也不会替你提交。
  git pull --rebase --autostash --quiet 2>/dev/null
  git add "_inbox/X/参考库" 2>/dev/null
  if git diff --cached --quiet; then
    echo "无变化，跳过提交"
  else
    git -c user.name="${GIT_USER_NAME:-x-radar}" -c user.email="${GIT_USER_EMAIL:-x-radar@local}" \
        commit -m "X参考库同步 $(TZ='Asia/Shanghai' date +%F)" --quiet
    if git push --quiet 2>/dev/null; then
      echo "已提交并推送"
    else
      # 远端又有人推了：再 rebase 一次后重推，仍失败就只保留本地提交
      git pull --rebase --autostash --quiet 2>/dev/null && git push --quiet 2>/dev/null \
        && echo "已提交并推送（二次同步后成功）" \
        || echo "已本地提交，推送失败（远端冲突，等下次重试）"
    fi
  fi
fi

# 3) 摘要给 cron 日志
echo "长文 $(find "$DST/长文" -name '*.md' 2>/dev/null | wc -l) 篇 · 短推合集 $(find "$DST/短推" -name '*.md' 2>/dev/null | wc -l) 个 · 仅摘要 $(find "$DST/_仅摘要" -name '*.md' 2>/dev/null | wc -l) 条"
exit 0
