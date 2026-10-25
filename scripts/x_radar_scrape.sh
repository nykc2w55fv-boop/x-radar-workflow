#!/bin/bash
# X 选题雷达 - 阶段一抓取脚本 (no_agent cron)
# 抓取 xzhishu 热门长文榜「全部」榜单，解析成结构化 JSON 快照，
# 供 08:00 的 agent cron 做 AI 领域选题分析。
#
# 产物:
#   ~/.hermes/x-radar/snapshot_<日期>.json    今日快照
#   ~/.hermes/x-radar/articles_history.jsonl  累计历史(每日追加, 供选题池积累)
#
# 安全/幂等: 全部落盘到 ~/.hermes/x-radar/ (持久目录, 禁放 /tmp)
set -uo pipefail

# 浏览器：优先 $CHROME_BIN，其次 Playwright 缓存里最新的 chromium，最后系统 chrome/chromium
if [ -n "${CHROME_BIN:-}" ]; then
  CHROME="$CHROME_BIN"
else
  CHROME=$(ls -1d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | sort -V | tail -1)
  [ -n "$CHROME" ] || CHROME=$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)
fi
[ -n "$CHROME" ] && [ -x "$CHROME" ] || { echo "ERROR: 找不到 Chrome/Chromium，请装浏览器或设置 CHROME_BIN" >&2; exit 1; }

WORK="${XRADAR_HOME:-$HOME/.hermes/x-radar}"
mkdir -p "$WORK" || exit 1

# 北京时间日期
RDATE=$(TZ='Asia/Shanghai' date +%F)
DOM_FILE="$WORK/dom_$RDATE.html"
SNAP_FILE="$WORK/snapshot_$RDATE.json"
HIST_FILE="$WORK/articles_history.jsonl"

# 1) 无头 Chrome 渲染抓 DOM (虚拟时间跑完 JS)。失败重试一次。
DOM_OK=0
for attempt in 1 2; do
  if timeout 90 "$CHROME" --headless=new --no-sandbox --disable-gpu \
      --dump-dom --virtual-time-budget=25000 \
      "https://xzhishu.com/rankings/articles" > "$DOM_FILE" 2>/dev/null; then
    DOM_OK=1
    break
  fi
  sleep 5
done
if [ "$DOM_OK" -ne 1 ]; then
  echo "ERROR: xzhishu DOM fetch failed" >&2
  exit 1
fi
[ -s "$DOM_FILE" ] || { echo "ERROR: empty DOM" >&2; exit 1; }

# 2) 解析 + 落盘
AUTH=$(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M')
SNAP_FILE="$SNAP_FILE" DOM_FILE="$DOM_FILE" HIST_FILE="$HIST_FILE" \
RDATE="$RDATE" python3 - <<'PYEOF'
import re, os, json, html as H
dom = open(os.environ['DOM_FILE'], encoding='utf-8', errors='replace').read()
card_re = re.compile(r'<a target="_blank" rel="noopener noreferrer" class="block" href="(https://x\.com/[^"]+/status/\d+)">(.*?)</a>', re.S)
seen, rows = set(), []
for href, inner in card_re.findall(dom):
    if href in seen: continue
    seen.add(href)
    def g(pat):
        m = re.search(pat, inner)
        return m.group(1) if m else ''
    badge = g(r'backdrop-blur-sm">([^<]+)</span>')
    title = g(r'role="heading" aria-level="2">([^<]+)</span>')
    summary = g(r'mt-2 line-clamp-2 [^"]*">([^<]+)</span>')
    handle = g(r'@([A-Za-z0-9_]+)</span>')
    time_raw = g(r'(\d+[hd]发布|刚刚发布|\d+小时前)')
    # 互动: [阅读, 点赞, 评论, 收藏] 按 lucide 图标出现顺序。图标后紧跟 </svg> 再是数字
    metric_order = ['chart-column', 'heart', 'message-circle', 'bookmark']
    raw = re.findall(r'class="lucide lucide-([\w-]+)[^"]*"[^>]*>.*?</svg>\s*([\d.,万]+)</span>', inner, re.S)
    mnum = {k: v for k, v in raw}
    vals = []
    def num(v):
        v = v.replace(',', '').strip()
        if v.endswith('万'):
            return int(float(v[:-1]) * 10000)
        return int(float(v)) if v else 0
    vals = [num(mnum.get(k, '0')) for k in metric_order]
    reads, likes, comments, bookmarks = vals
    rows.append({
        'date': os.environ['RDATE'],
        'handle': handle, 'href': href, 'badge': badge,
        'title': H.unescape(title).strip(),
        'summary': H.unescape(summary).strip(),
        'time_raw': time_raw,
        'reads': reads, 'likes': likes, 'comments': comments, 'bookmarks': bookmarks,
    })
snapshot = {'date': os.environ['RDATE'], 'fetched_at': 'FETCHED_AT_PLACEHOLDER',
            'source': 'https://xzhishu.com/rankings/articles', 'count': len(rows), 'articles': rows}
snapshot['fetched_at'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
with open(os.environ['SNAP_FILE'], 'w', encoding='utf-8') as f:
    json.dump(snapshot, f, ensure_ascii=False, indent=1)
# 累计历史 (按 href 去重追加)
existing = set()
if os.path.exists(os.environ['HIST_FILE']):
    for line in open(os.environ['HIST_FILE'], encoding='utf-8'):
        try: existing.add(json.loads(line)['href'])
        except Exception: pass
with open(os.environ['HIST_FILE'], 'a', encoding='utf-8') as f:
    for r in rows:
        if r['href'] not in existing:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f"OK snapshot={os.path.basename(os.environ['SNAP_FILE'])} articles={len(rows)}")
# 摘要: 阅读TOP3 + AI候选数(供日志)
ai_kw = re.compile(r'AI|ChatGPT|Claude|LLM|OpenAI|Gemini|DeepSeek|豆包|大模型|Agent|机器人|模型|Codex|生成|自动化|GPT|Midjourney|视频生成|Sora|Copilot|智能', re.I)
ai_n = sum(1 for r in rows if ai_kw.search(r['title'] + ' ' + r['summary']))
print(f"AI_candidates={ai_n}/total={len(rows)}")
PYEOF
