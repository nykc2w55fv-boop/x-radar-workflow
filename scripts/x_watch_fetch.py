#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X 对标账号监控（免费通道：api.fxtwitter.com）

用途
  绕过 xzhishu 榜单，直接盯住一份「对标账号名单」，抓它们最近 N 小时的新帖与
  新长文（X Article），去重后落盘，供 08:00 的选题雷达 agent 合并使用。

用法
  python3 x_watch_fetch.py                # 默认 36 小时窗口，每号取 12 条
  python3 x_watch_fetch.py --hours 72
  python3 x_watch_fetch.py --count 20 --min-likes 20
  python3 x_watch_fetch.py --list         # 只打印名单与上次抓取状态

产物（全部在 ~/.hermes/x-radar/）
  watch_<北京时间日期>.json   结构化结果
  watch_<北京时间日期>.md     给 agent / 人读的中文清单
  watch_seen.json            已推送过的推文 id（去重水位）

说明
  · 纯 urllib，无第三方依赖；每个账号之间 sleep 1.2s 礼貌抓取。
  · 单账号失败不影响整体，只在 md 末尾「抓取异常」里记一行。
  · 长文（text 只是 article 链接，或 is_note_tweet）会额外调 /2/status/<id> 取全文。
  · 无价格：fxtwitter 免费。缺点是非官方维护，挂了要人工换通道（x_search_fetch.py）。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

WORK = os.path.expanduser(os.environ.get('XRADAR_HOME') or '~/.hermes/x-radar')
WATCH_FILE = os.path.join(WORK, 'watch_accounts.txt')
SEEN_FILE = os.path.join(WORK, 'watch_seen.json')
UA = {'User-Agent': 'Mozilla/5.0'}
BJ = timezone(timedelta(hours=8))
API = 'https://api.fxtwitter.com'
ARTICLE_RE = re.compile(r'x\.com/i/article/\d+|t\.co/')


def load_watch():
    """返回 [(分类, handle)]，分类取自 [..] 行。"""
    rows, cat = [], '未分类'
    if not os.path.exists(WATCH_FILE):
        sys.exit(f'ERROR: 名单文件不存在 {WATCH_FILE}')
    for raw in open(WATCH_FILE, encoding='utf-8'):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[') and line.endswith(']'):
            cat = line.strip('[]')
            continue
        rows.append((cat, line.lstrip('@')))
    return rows


def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8', errors='replace'))


def get_json_retry(url, attempts=3, backoff=4):
    """fxtwitter 偶尔对某些账号回 404/429（访客池抖动），重试能救回大部分。"""
    last = None
    for i in range(attempts):
        try:
            return get_json(url)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 429, 500, 502, 503):
                time.sleep(backoff * (i + 1))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(backoff * (i + 1))
    raise last


def fetch_article_text(tid, handle):
    """长文正文：/2/status/<id> → article.content.blocks；退回 tweet.text。"""
    try:
        d = get_json(f'{API}/2/status/{tid}')
    except Exception:
        return None
    # 坑：/2/status/<id> 顶层键是 status，/<handle>/status/<id> 才是 tweet，两个都要认
    tw = d.get('tweet') or d.get('status') or {}
    blocks = ((tw.get('article') or {}).get('content') or {}).get('blocks') or []
    if blocks:
        return '\n\n'.join(b.get('text', '') for b in blocks if b.get('text'))
    return (tw.get('text') or '').strip() or None


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {'ids': [], 'updated': None}
    try:
        return json.load(open(SEEN_FILE, encoding='utf-8'))
    except Exception:
        return {'ids': [], 'updated': None}


def save_seen(seen, keep=4000):
    ids = seen.get('ids', [])[-keep:]
    json.dump({'ids': ids, 'updated': datetime.now(BJ).strftime('%Y-%m-%d %H:%M:%S')},
              open(SEEN_FILE, 'w', encoding='utf-8'), ensure_ascii=False)


def fmt_bj(ts):
    return datetime.fromtimestamp(ts, BJ).strftime('%m-%d %H:%M')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=float, default=36, help='回看窗口（小时），默认 36')
    ap.add_argument('--count', type=int, default=12, help='每号取多少条，默认 12')
    ap.add_argument('--min-likes', type=int, default=0, help='点赞门槛，默认 0')
    ap.add_argument('--list', action='store_true', help='只打印名单')
    ap.add_argument('--force', action='store_true', help='忽略去重水位，重抓全部')
    args = ap.parse_args()

    watch = load_watch()
    if args.list:
        seen = load_seen()
        last = seen.get('updated') or '从未'
        print(f'名单 {len(watch)} 个账号 · 去重水位 {len(seen.get("ids", []))} 条 · 上次抓取 {last}')
        for cat, h in watch:
            print(f'  [{cat}] {h}')
        return

    os.makedirs(WORK, exist_ok=True)
    now = datetime.now(BJ)
    since_ts = (now - timedelta(hours=args.hours)).timestamp()
    seen = load_seen()
    seen_ids = set() if args.force else set(seen.get('ids', []))
    new_ids = []

    items, errors = [], []
    for cat, handle in watch:
        try:
            d = get_json_retry(f'{API}/2/profile/{handle}/statuses?count={args.count}')
            results = d.get('results') or []
        except Exception as e:
            errors.append(f'{handle}: {str(e)[:70]}')
            time.sleep(1.2)
            continue
        for r in results:
            cts = r.get('created_timestamp') or 0
            if cts < since_ts:
                continue
            if r.get('reposted_by'):
                continue          # 转推，不是原创
            if r.get('replying_to'):
                continue          # 回帖，噪声大
            if (r.get('likes') or 0) < args.min_likes:
                continue
            tid = r.get('id')
            if not tid or tid in seen_ids:
                continue
            text = (r.get('text') or '').strip()
            is_article = bool(r.get('is_note_tweet')) or bool(ARTICLE_RE.search(text))
            full = None
            if is_article:
                full = fetch_article_text(tid, handle)
                time.sleep(0.6)
            body = full or text
            if len(body) < 60:
                continue          # 一句话动态，没有选题价值
            items.append({
                'handle': handle,
                'category': cat,
                'id': tid,
                'url': r.get('url'),
                'created_at_bj': fmt_bj(cts),
                'created_ts': cts,
                'followers': (r.get('author') or {}).get('followers'),
                'likes': r.get('likes', 0),
                'views': r.get('views', 0),
                'bookmarks': r.get('bookmarks', 0),
                'replies': r.get('replies', 0),
                'lang': r.get('lang'),
                'is_article': is_article,
                'excerpt': body[:200].replace('\n', ' '),
                'text': body,
            })
            new_ids.append(tid)
            seen_ids.add(tid)
        time.sleep(1.2)

    day = now.strftime('%Y-%m-%d')
    jf = os.path.join(WORK, f'watch_{day}.json')
    mf = os.path.join(WORK, f'watch_{day}.md')
    new_count = len(items)
    # 同一天重复运行（手动补抓）时不要覆盖上午的成果：把旧结果并回来
    if os.path.exists(jf):
        try:
            old = json.load(open(jf, encoding='utf-8')).get('items') or []
            known = {x['id'] for x in items}
            items = items + [x for x in old if x.get('id') not in known]
        except Exception:
            pass
    items.sort(key=lambda x: (-(x['likes'] or 0), -x['created_ts']))
    TOP_N = 28
    # 只展示当前名单里的账号：换名单后，旧账号的历史条目留在 json 里但不进 md，避免误导
    cur = {h.lower() for _, h in watch}
    cur_items = [x for x in items if (x.get('handle') or '').lower() in cur]
    hidden = len(items) - len(cur_items)
    show = sorted(cur_items, key=lambda x: (0 if x['is_article'] else 1, -(x['likes'] or 0)))[:TOP_N]
    json.dump({'date': day, 'fetched_at': now.strftime('%Y-%m-%d %H:%M:%S'),
               'window_hours': args.hours, 'accounts': len(watch),
               'new_count': new_count, 'total_count': len(items),
               'errors': errors, 'items': items},
              open(jf, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    lines = [f'# 对标账号监控 · {day} {now.strftime("%H:%M")}（回看 {args.hours:g} 小时）', '',
             f'名单 {len(watch)} 个 · 本次新增 {new_count} 条 · 当日累计 {len(items)} 条 · 异常 {len(errors)} 个', '']
    if hidden:
        lines += [f'其中 {hidden} 条来自已移出名单的账号，不在此列出（仍在 watch_{day}.json 里）。', '']
    if len(cur_items) > len(show):
        lines.append(f'下面按「长文优先 + 点赞优先」列出前 {len(show)} 条，其余 {len(cur_items) - len(show)} 条见 watch_{day}.json。')
        lines.append('')
    if not items:
        lines.append('本期无新内容。')
    for it in show:
        tag = '长文' if it['is_article'] else '推文'
        lines.append(f"## [{it['category']}] @{it['handle']} · {tag} · {it['created_at_bj']}")
        lines.append(f"- 链接：{it['url']}")
        lines.append(f"- 数据：赞 {it['likes']} / 回 {it['replies']} / 阅 {it['views']} / 藏 {it['bookmarks']} / 粉丝 {it['followers']}")
        body = it['text'] if it['is_article'] else it['excerpt']
        # 只给开头，正文要用时再调 x_radar_fetch.py 取全文——控制 agent 上下文体积
        preview = body[:420] if it['is_article'] else body[:180]
        lines.append('- 正文：' + preview.replace('\n', ' '))
        lines.append('')
    if errors:
        lines += ['## 抓取异常', ''] + [f'- {e}' for e in errors] + ['']
    open(mf, 'w', encoding='utf-8').write('\n'.join(lines))

    seen['ids'] = seen.get('ids', []) + new_ids
    save_seen(seen)
    print(f'OK {mf} 本次新增{new_count}条 累计{len(items)}条 异常{len(errors)}个')


if __name__ == '__main__':
    main()
