#!/usr/bin/env bash
# x_watch_all.sh — 07:50 对标账号监控（no_agent）
#   1) x_watch_fetch.py  免费通道，抓关注名单的新帖/新长文
#   2) x_search_fetch.py 付费通道，关键词搜索（无 key 时自己静默跳过）
# 两个脚本各自失败都不影响另一个；整体永远 exit 0，避免定时任务红叉刷屏。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 0

echo "=== 对标账号 ==="
timeout 600 python3 "$DIR/x_watch_fetch.py" --hours 36 2>&1 | tail -5

echo "=== 关键词 ==="
timeout 300 python3 "$DIR/x_search_fetch.py" 2>&1 | tail -5

exit 0
