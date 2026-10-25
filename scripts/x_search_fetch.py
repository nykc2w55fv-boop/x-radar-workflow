#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X 关键词监控（付费通道：twitterapi.io，按条计费）

定位
  fxtwitter 的搜索接口 404 不可用，所以「按关键词找话题」只能用付费通道。
  本脚本费用敏感设计：默认每个查询只翻 1 页（最多 20 条），命中后按点赞过滤，
  6 条查询 × 1 页 ≈ $0.018/天 ≈ $0.55/月。宁少不滥。

用法
  python3 x_search_fetch.py --probe          # 只验 key 是否有效 + 余额，最便宜
  python3 x_search_fetch.py                  # 跑 watch_queries.txt 全部查询
  python3 x_search_fetch.py --pages 2
  python3 x_search_fetch.py --query '"一人公司" lang:zh'

Key 放哪
  ~/.hermes/.env 里写一行：TWITTERAPI_IO_KEY=xxxx
  或临时：TWITTERAPI_IO_KEY=xxxx python3 x_search_fetch.py
  没有 key 时脚本静默跳过（exit 0），不会让定时任务报错。

产物
  ~/.hermes/x-radar/search_<北京时间日期>.json / .md
  ~/.hermes/x-radar/search_seen.json  去重水位

价格（twitterapi.io 官网原文，2026-10 查）
  $0.15 / 1000 条推文；每请求最低 $0.00015；100,000 credits = $1.00
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

WORK = os.path.expanduser(os.environ.get('XRADAR_HOME') or '~/.hermes/x-radar')
ENV_FILE = os.path.expanduser(os.environ.get('XRADAR_ENV') or '~/.hermes/.env')
QUERY_FILE = os.path.join(WORK, 'watch_queries.txt')
SEEN_FILE = os.path.join(WORK, 'search_seen.json')
BASE = 'https://api.twitterapi.io'
BJ = timezone(timedelta(hours=8))
UA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
ARTICLE_RE = re.compile(r'x\.com/i/article/\d+')


def load_key():
    key = os.environ.get('TWITTERAPI_IO_KEY', '').strip()
    if key:
        return key
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding='utf-8'):
            line = line.strip()
            if line.startswith('TWITTERAPI_IO_KEY'):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def api(path, key, params=None, timeout=35):
    url = BASE + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={**UA, 'X-API-Key': key})
    # 免费档有 QPS 限制（实测 429 "For free-tier users..."），单发不重试会整天漏抓
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8', errors='replace'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:300]
            last = RuntimeError(f'HTTP {e.code} {body}')
            if e.code in (429, 500, 502, 503):
                time.sleep(5 * (attempt + 1))
                continue
            raise last
    raise last


def fxtwitter_article(tid):
    """长文正文兜底：fxtwitter 免费取 article blocks。"""
    try:
        req = urllib.request.Request(f'https://api.fxtwitter.com/2/status/{tid}', headers=UA)
        with urllib.request.urlopen(req, timeout=25) as resp:
            d = json.loads(resp.read().decode('utf-8', errors='replace'))
        # 坑：/2/status/<id> 顶层键是 status，不是 tweet
        tw = d.get('tweet') or d.get('status') or {}
        blocks = ((tw.get('article') or {}).get('content') or {}).get('blocks') or []
        if blocks:
            return '\n\n'.join(b.get('text', '') for b in blocks if b.get('text'))
        return (tw.get('text') or '').strip() or None
    except Exception:
        return None


def load_queries():
    if not os.path.exists(QUERY_FILE):
        sys.exit(f'ERROR: 查询文件不存在 {QUERY_FILE}')
    return [l.strip() for l in open(QUERY_FILE, encoding='utf-8')
            if l.strip() and not l.strip().startswith('#')]


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        return set(json.load(open(SEEN_FILE, encoding='utf-8')).get('ids', []))
    except Exception:
        return set()


def save_seen(ids, keep=6000):
    lst = list(ids)[-keep:]
    json.dump({'ids': lst, 'updated': datetime.now(BJ).strftime('%Y-%m-%d %H:%M:%S')},
              open(SEEN_FILE, 'w', encoding='utf-8'), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', action='store_true', help='只验 key 有效性')
    ap.add_argument('--query', help='只跑这一条查询')
    ap.add_argument('--pages', type=int, default=1, help='每条查询翻几页（每页≤20条），默认 1')
    ap.add_argument('--min-likes', type=int, default=20, help='点赞门槛，默认 20')
    ap.add_argument('--min-chars', type=int, default=80, help='正文最少字数，默认 80')
    args = ap.parse_args()

    key = load_key()
    if not key:
        print(f'SKIP: 未配置 TWITTERAPI_IO_KEY（{ENV_FILE}），关键词通道暂不启用。')
        return 0

    if args.probe:
        try:
            d = api('/twitter/tweet/advanced_search', key,
                    {'query': 'AI lang:zh', 'queryType': 'Latest'})
            n = len(d.get('tweets') or [])
            print(f'OK key 有效，返回 {n} 条样本；响应顶层字段：{list(d.keys())}')
        except Exception as e:
            print(f'FAIL: {e}')
            return 1
        return 0

    queries = [args.query] if args.query else load_queries()
    seen = load_seen()
    new_ids, items, errors = [], [], []
    now = datetime.now(BJ)
    cutoff = (now - timedelta(days=4)).timestamp()   # 只要最近 4 天的，避免翻出陈年旧帖

    for q in queries:
        cursor = None
        for page in range(args.pages):
            params = {'query': q, 'queryType': 'Latest'}
            if cursor:
                params['cursor'] = cursor
            try:
                d = api('/twitter/tweet/advanced_search', key, params)
            except Exception as e:
                errors.append(f'{q[:30]}: {str(e)[:80]}')
                break
            tweets = d.get('tweets') or []
            for t in tweets:
                tid = str(t.get('id') or '')
                if not tid or tid in seen:
                    continue
                if (t.get('likeCount') or 0) < args.min_likes:
                    continue
                if t.get('isReply'):
                    continue
                text = (t.get('text') or '').strip()
                if len(text) < args.min_chars:
                    continue
                # 时间过滤（createdAt 形如 "Wed Oct 22 10:00:00 +0000 2026"）
                ts = 0
                try:
                    ts = datetime.strptime(t['createdAt'], '%a %b %d %H:%M:%S %z %Y').timestamp()
                except Exception:
                    pass
                if ts and ts < cutoff:
                    continue
                is_article = bool(ARTICLE_RE.search(text))
                body = fxtwitter_article(tid) if is_article else None
                author = t.get('author') or {}
                items.append({
                    'query': q,
                    'handle': author.get('userName'),
                    'name': author.get('name'),
                    'followers': author.get('followers'),
                    'id': tid,
                    'url': t.get('url') or f"https://x.com/{author.get('userName')}/status/{tid}",
                    'created_at_bj': datetime.fromtimestamp(ts, BJ).strftime('%m-%d %H:%M') if ts else '',
                    'created_ts': ts,
                    'likes': t.get('likeCount', 0),
                    'views': t.get('viewCount', 0),
                    'bookmarks': t.get('bookmarkCount', 0),
                    'replies': t.get('replyCount', 0),
                    'is_article': is_article,
                    'text': (body or text)[:3000],
                })
                new_ids.append(tid)
                seen.add(tid)
            cursor = d.get('next_cursor') or (d.get('cursor') or {}).get('bottom')
            if not cursor or not d.get('has_next_page'):
                break
            time.sleep(1.0)
        time.sleep(1.0)

    items.sort(key=lambda x: (-(x['likes'] or 0), -x['created_ts']))
    new_count = len(items)          # 本次抓到的条数（合并前）
    day = now.strftime('%Y-%m-%d')
    jf = os.path.join(WORK, f'search_{day}.json')
    # 同一天重复运行（补抓/调试）不要把上午的成果冲掉：把旧结果并回来
    if os.path.exists(jf):
        try:
            old = json.load(open(jf, encoding='utf-8')).get('items') or []
            known = {x['id'] for x in items}
            items = items + [x for x in old if x.get('id') not in known]
            items.sort(key=lambda x: (-(x['likes'] or 0), -x['created_ts']))
        except Exception:
            pass
    json.dump({'date': day, 'fetched_at': now.strftime('%Y-%m-%d %H:%M:%S'),
               'queries': len(queries), 'new_count': new_count, 'total_count': len(items),
               'errors': errors, 'items': items},
              open(jf, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    lines = [f'# X 关键词命中 · {day} {now.strftime("%H:%M")}', '',
             f'查询 {len(queries)} 条 · 本次新增 {new_count} 条 · 当日累计 {len(items)} 条 · 异常 {len(errors)} 个', '']
    # md 是给 08:00 agent 读的：只留前 25 条、正文截 400 字，全量在 json 里，避免撑爆上下文
    for it in items[:25]:
        tag = '长文' if it['is_article'] else '推文'
        lines.append(f"## @{it['handle']}（{it['name']}）· {tag} · {it['created_at_bj']}")
        lines.append(f"- 命中查询：{it['query']}")
        lines.append(f"- 链接：{it['url']}")
        lines.append(f"- 数据：赞 {it['likes']} / 回 {it['replies']} / 阅 {it['views']} / 藏 {it['bookmarks']} / 粉丝 {it['followers']}")
        lines.append('- 正文：' + it['text'][:400].replace('\n', ' '))
        lines.append('')
    if len(items) > 25:
        lines += [f'其余 {len(items) - 25} 条见 search_{day}.json。', '']
    if errors:
        lines += ['## 异常', ''] + [f'- {e}' for e in errors] + ['']
    open(os.path.join(WORK, f'search_{day}.md'), 'w', encoding='utf-8').write('\n'.join(lines))
    save_seen(seen)
    print(f'OK search_{day}.md 本次新增{new_count}条 当日累计{len(items)}条 异常{len(errors)}个')
    return 0


if __name__ == '__main__':
    sys.exit(main())
