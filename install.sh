#!/usr/bin/env bash
# install.sh —— 一条命令把这套工作流的本地环境准备好
#
# 它做四件事，全部可重复执行（幂等，不会覆盖你已有的配置）：
#   1. 检查 python3 版本
#   2. 建数据目录 ${XRADAR_HOME:-~/.hermes/x-radar}
#   3. 从模板生成 watch_accounts.txt / watch_queries.txt（已存在就跳过）
#   4. 生成 ${XRADAR_ENV:-~/.hermes/.env}，没有就创建，有就只补缺的键
#
# 用法：
#   bash install.sh
#   XRADAR_HOME=~/x-radar bash install.sh      # 换个数据目录
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${XRADAR_HOME:-$HOME/.hermes/x-radar}"
ENVF="${XRADAR_ENV:-$HOME/.hermes/.env}"

say() { printf '  %s\n' "$*"; }

echo "==> 1/4 检查 python3"
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: 没装 python3。Debian/Ubuntu: sudo apt install python3；macOS: brew install python3" >&2
  exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PYOK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,8) else 0)')
if [ "$PYOK" != "1" ]; then
  echo "ERROR: python3 版本 $PYV 太低，需要 3.8 以上" >&2
  exit 1
fi
say "python3 $PYV OK"

echo "==> 2/4 建数据目录"
mkdir -p "$WORK" || { echo "ERROR: 建不了 $WORK" >&2; exit 1; }
say "$WORK"

echo "==> 3/4 配置文件"
if [ -f "$WORK/watch_accounts.txt" ]; then
  say "watch_accounts.txt 已存在，保持不动"
else
  cp "$DIR/config/watch_accounts.example.txt" "$WORK/watch_accounts.txt"
  say "watch_accounts.txt 已从示例生成 —— 记得改成你自己的名单"
fi
if [ -f "$WORK/watch_queries.txt" ]; then
  say "watch_queries.txt 已存在，保持不动"
else
  cp "$DIR/config/watch_queries.example.txt" "$WORK/watch_queries.txt"
  say "watch_queries.txt 已从示例生成"
fi

echo "==> 4/4 密钥文件"
mkdir -p "$(dirname "$ENVF")"
if [ ! -f "$ENVF" ]; then
  cp "$DIR/.env.example" "$ENVF"
  chmod 600 "$ENVF"
  say "$ENVF 已新建（权限 600）"
else
  say "$ENVF 已存在，未改动"
fi

echo
echo "==> 冒烟测试（只读名单，不发请求）"
python3 "$DIR/scripts/x_watch_fetch.py" --list || true

cat <<EOF

装好了。接下来：

  1. 改名单:      \$EDITOR $WORK/watch_accounts.txt
  2. 跑账号监控:  python3 $DIR/scripts/x_watch_fetch.py --hours 36
  3. 跑榜单:      bash $DIR/scripts/x_radar_scrape.sh      # 需要 Chrome/Chromium
  4. 跑精选:      python3 $DIR/scripts/aihot_fetch.py
  5. 抓长文全文:  python3 $DIR/scripts/x_radar_fetch.py https://x.com/<handle>/status/<id>
  6. 归集成库:    python3 $DIR/scripts/build_x_library.py

关键词通道（可选，要花钱）：
  在 $ENVF 里填 TWITTERAPI_IO_KEY=xxx，然后
  python3 $DIR/scripts/x_search_fetch.py --probe     # 先验 key
  python3 $DIR/scripts/x_search_fetch.py             # 再跑全量查询

想每天自动跑，把 scripts/x_watch_all.sh 挂进 crontab 或你所用 agent 的定时任务。
EOF
