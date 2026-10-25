#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X 参考库构建器 —— 把本机所有抓到过的 X 原文归到一个位置（可选排除你自己的号）。

来源（全部只读，不改原文件）
  1. ~/.hermes/x-radar/article_<id>.txt     fxtwitter 抓的长文正文
  2. ~/.hermes/x-radar/wealth_<id>.txt      财富号筛出来的长文正文
  3. ~/.hermes/x-radar/watch_*.json         对标账号监控（长文+短推，含元数据）
  4. ~/.hermes/x-radar/search_*.json        关键词命中（同上）
  5. ~/.hermes/x-radar/articles_history.jsonl + snapshot_*.json
                                            只有标题与摘要的（原文没抓过）→ 单独放 _仅摘要

产物
  ~/x-reference/_store.jsonl      主库（一行一条，按 tweet id 去重，唯一的真源）
  ~/x-reference/长文/<YYYY-MM>/<id>__<handle>__<标题>.md
  ~/x-reference/短推/<handle>/<YYYY-MM>.md        同一账号同月合成一篇，便于通读
  ~/x-reference/_仅摘要/长文/<YYYY-MM>/...         只有摘要的，明确标注「原文未抓」
  ~/x-reference/索引.csv、索引.md、README.md

用法
  python3 build_x_library.py --scan     # 只看清单，不写文件
  python3 build_x_library.py            # 构建/增量更新（每次全量重渲染，幂等）
  python3 build_x_library.py --no-live  # 缺元数据时不去 fxtwitter 补，用占位
"""
import argparse
import csv
import glob
import json
import os
import re
import shutil
import time
import urllib.request
from datetime import datetime, timedelta, timezone

RADAR = os.path.expanduser(os.environ.get('XRADAR_HOME') or '~/.hermes/x-radar')
OUT = os.path.expanduser(os.environ.get('XRADAR_LIBRARY') or '~/x-reference')
STORE = os.path.join(OUT, '_store.jsonl')
LIVE_CACHE = os.path.join(RADAR, '_live_cache.json')
SELF_HANDLE = os.environ.get('XRADAR_SELF_HANDLE', '').lstrip('@')   # 你自己的号，可选：填了就不把你自己抓进库
WATCH_FILE = os.path.join(RADAR, 'watch_accounts.txt')
BJ = timezone(timedelta(hours=8))
UA = {'User-Agent': 'Mozilla/5.0'}
STATUS_ID_RE = re.compile(r'(?:status/|article_|wealth_)(\d{12,25})')
LONG_CHARS = 900                    # 不是 X Article 但正文超过这个字数，也算长文


def bj(ts):
    return datetime.fromtimestamp(ts, BJ).strftime('%Y-%m-%d %H:%M') if ts else ''


# ---------------- 读来源 ----------------

def load_meta():
    """从历史 jsonl + 快照收集元数据：id -> {handle,title,summary,url,metrics}"""
    meta = {}
    hist = os.path.join(RADAR, 'articles_history.jsonl')
    rows = []
    if os.path.exists(hist):
        for line in open(hist, encoding='utf-8'):
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    for f in glob.glob(os.path.join(RADAR, 'snapshot_*.json')):
        try:
            rows += json.load(open(f, encoding='utf-8')).get('articles', [])
        except Exception:
            pass
    for r in rows:
        m = STATUS_ID_RE.search(r.get('href', '') or '')
        if not m:
            continue
        tid = m.group(1)
        meta.setdefault(tid, {
            'id': tid,
            'handle': (r.get('handle') or '').strip(),
            'url': r.get('href'),
            'title': (r.get('title') or '').strip(),
            'summary': (r.get('summary') or '').strip(),
            'likes': r.get('likes'),
            'views': r.get('reads'),
            'bookmarks': r.get('bookmarks'),
            'replies': r.get('comments'),
        })
    return meta


def load_structured():
    """watch_*.json / search_*.json 里的完整条目：id -> record"""
    out = {}
    for pat in ('watch_*.json', 'search_*.json'):
        for f in sorted(glob.glob(os.path.join(RADAR, pat))):
            try:
                d = json.load(open(f, encoding='utf-8'))
            except Exception:
                continue
            for it in d.get('items') or []:
                tid = str(it.get('id') or '')
                if not tid:
                    continue
                rec = out.setdefault(tid, {})
                rec.update({
                    'id': tid,
                    'handle': it.get('handle') or rec.get('handle', ''),
                    'url': it.get('url') or rec.get('url'),
                    'created_ts': it.get('created_ts') or rec.get('created_ts'),
                    'likes': it.get('likes'),
                    'views': it.get('views'),
                    'bookmarks': it.get('bookmarks'),
                    'replies': it.get('replies'),
                    'followers': it.get('followers'),
                    'is_article': bool(it.get('is_article')),
                    'text': (it.get('text') or '').strip(),
                })
    return out


def load_raw_texts():
    """article_*.txt / wealth_*.txt：id -> {text, src}"""
    out = {}
    for pat, src in (('article_*.txt', 'fxtwitter'), ('wealth_*.txt', 'xzhishu财富号')):
        for f in glob.glob(os.path.join(RADAR, pat)):
            m = STATUS_ID_RE.search(os.path.basename(f))
            if not m:
                continue
            tid = m.group(1)
            try:
                text = open(f, encoding='utf-8', errors='replace').read().strip()
            except Exception:
                continue
            if not text:
                continue
            rec = out.setdefault(tid, {'id': tid, 'text': '', 'src': src})
            if len(text) > len(rec['text']):
                rec['text'] = text
    return out


def live_meta(tid):
    """元数据缺失时现查 fxtwitter（只取元信息，正文已有就不覆盖）

    注意：/2/status/<id> 返回的顶层键是 status（不是 tweet），早期写法按 tweet 解析会静默拿到空。
    """
    try:
        req = urllib.request.Request(f'https://api.fxtwitter.com/2/status/{tid}', headers=UA)
        with urllib.request.urlopen(req, timeout=25) as resp:
            d = json.loads(resp.read().decode('utf-8', errors='replace'))
        tw = d.get('tweet') or d.get('status') or {}
        au = tw.get('author') or (d.get('author') or {})
        art = tw.get('article') or {}
        blocks = ((art.get('content') or {}).get('blocks')) or []
        body = '\n\n'.join(b.get('text', '') for b in blocks if b.get('text')) if blocks else ''
        if not body:
            body = (tw.get('text') or '').strip()
        # 正文只是一行 article 链接时，视为没抓到
        if re.fullmatch(r'https://x\.com/i/article/\d+', body or ''):
            body = ''
        return {
            'handle': au.get('screen_name') or '',
            'author_name': au.get('name') or '',
            'followers': au.get('followers'),
            'url': tw.get('url') or f'https://x.com/{au.get("screen_name","i")}/status/{tid}',
            'created_ts': tw.get('created_timestamp'),
            'likes': tw.get('likes'),
            'views': tw.get('views'),
            'bookmarks': tw.get('bookmarks'),
            'replies': tw.get('replies'),
            'title': (art.get('title') or '').strip(),
            'is_article': bool(blocks) or bool(tw.get('is_note_tweet')),
            'text': body,
        }
    except Exception:
        return {}


# ---------------- 合并 ----------------

def build_store(live=True, verbose=True):
    meta = load_meta()
    structured = load_structured()
    raw = load_raw_texts()
    # 现查结果的缓存：不然每次重建都要为同一批「只有摘要」的帖子重新请求 200 多次
    try:
        cache = json.load(open(LIVE_CACHE, encoding='utf-8'))
    except Exception:
        cache = {}

    ids = set(meta) | set(structured) | set(raw)
    records = []
    live_calls = 0

    for tid in ids:
        rec = {'id': tid}
        m = meta.get(tid) or {}
        s = structured.get(tid) or {}
        r = raw.get(tid) or {}
        c = cache.get(tid) or {}

        text = (s.get('text') or '').strip() or (r.get('text') or '').strip() or (c.get('text') or '').strip()
        handle = s.get('handle') or m.get('handle') or c.get('handle') or ''
        title = m.get('title') or c.get('title') or ''
        created = s.get('created_ts') or c.get('created_ts')

        need_live = (not text) or (not handle) or (not created)
        if need_live and live:
            lm = live_meta(tid)
            live_calls += 1
            time.sleep(0.5)
            if lm:
                cache[tid] = lm
                handle = handle or lm.get('handle') or ''
                created = created or lm.get('created_ts')
                title = title or lm.get('title') or ''
                rec['author_name'] = lm.get('author_name') or ''
                rec['followers'] = s.get('followers') or lm.get('followers')
                for k in ('likes', 'views', 'bookmarks', 'replies'):
                    if s.get(k) is None and m.get(k) is None:
                        rec[k] = lm.get(k)
                if not text and lm.get('text'):
                    text = lm['text']
                if lm.get('is_article'):
                    s['is_article'] = True
                rec['url'] = s.get('url') or m.get('url') or lm.get('url')
        elif c:
            # 用缓存兜底
            handle = handle or c.get('handle') or ''
            created = created or c.get('created_ts')
            title = title or c.get('title') or ''
            if c.get('is_article'):
                s['is_article'] = True
            rec['author_name'] = rec.get('author_name') or c.get('author_name') or ''
            for k in ('likes', 'views', 'bookmarks', 'replies', 'followers'):
                if s.get(k) is None and m.get(k) is None and rec.get(k) is None:
                    rec[k] = c.get(k)

        rec.update({
            'handle': handle,
            'url': s.get('url') or m.get('url') or rec.get('url') or f'https://x.com/{handle}/status/{tid}',
            'created_ts': created,
            'likes': s.get('likes', m.get('likes')),
            'views': s.get('views', m.get('views')),
            'bookmarks': s.get('bookmarks', m.get('bookmarks')),
            'replies': s.get('replies', m.get('replies')),
            'followers': s.get('followers', rec.get('followers')),
            'title': title,
            'summary': m.get('summary') or '',
            'text': text,
            'source': '、'.join(x for x in (r.get('src'), 'watch' if tid in structured else '') if x) or '仅榜单摘要',
        })
        body = rec['text'] or rec['summary']
        rec['is_article'] = bool(s.get('is_article')) or len(body) >= LONG_CHARS or bool(rec['title'])
        records.append(rec)

    # 排除本人（未配置 XRADAR_SELF_HANDLE 时全部保留）
    self_lower = SELF_HANDLE.lower()
    kept, dropped = [], 0
    for rec in records:
        h = (rec.get('handle') or '').lower()
        if self_lower and (h == self_lower or f'/{SELF_HANDLE}/' in (rec.get('url') or '')):
            dropped += 1
            continue
        kept.append(rec)

    kept.sort(key=lambda x: (-(x.get('created_ts') or 0), x['id']))
    try:
        json.dump(cache, open(LIVE_CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass
    if verbose:
        print(f'来源合计 {len(ids)} 条 · 排除本人 {dropped} 条 · 入库 {len(kept)} 条'
              f' · 现查元数据 {live_calls} 次')
    return kept


def save_store(recs):
    os.makedirs(OUT, exist_ok=True)
    with open(STORE, 'w', encoding='utf-8') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


# ---------------- 渲染 ----------------

def slug(s, n=28):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]', '', s or '').strip()
    s = re.sub(r'\s+', ' ', s)
    return s[:n].strip() or '无标题'


def ymd(rec):
    ts = rec.get('created_ts')
    return datetime.fromtimestamp(ts, BJ).strftime('%Y-%m') if ts else '未知日期'


def entry_md(rec):
    lines = ['---']
    for k in ('id', 'handle', 'author_name', 'url', 'likes', 'views', 'bookmarks', 'replies', 'followers', 'source'):
        v = rec.get(k)
        if v not in (None, ''):
            lines.append(f'{k}: {v}')
    if rec.get('created_ts'):
        lines.append(f'created_at: {bj(rec["created_ts"])}')
    if rec.get('title'):
        lines.append(f'title: "{rec["title"][:80]}"')
    lines.append('---')
    lines.append('')
    if rec.get('title'):
        lines.append(f"# {rec['title']}")
        lines.append('')
    head = f"> 作者 @{rec.get('handle') or '未知'} · {bj(rec.get('created_ts'))} · {rec.get('url')}"
    lines.append(head)
    lines.append('')
    body = rec.get('text') or ''
    if not body:
        lines.append('> ⚠️ 本条只抓到了榜单标题与摘要，**原文没抓过**。')
        lines.append('')
        body = rec.get('summary') or ''
    lines.append(body)
    lines.append('')
    return '\n'.join(lines)


def current_handles():
    """当前监控名单里的账号（小写）。名单缺失时返回 None 表示「不过滤」。"""
    if not os.path.exists(WATCH_FILE):
        return None
    out = set()
    for line in open(WATCH_FILE, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('['):
            continue
        out.add(line.lstrip('@').lower())
    return out or None


def render(recs, current_only=False):
    # 清空渲染目录（_store.jsonl 保留）
    for sub in ('长文', '短推', '_仅摘要'):
        p = os.path.join(OUT, sub)
        if os.path.isdir(p):
            shutil.rmtree(p)
        os.makedirs(p, exist_ok=True)

    allowed = current_handles() if current_only else None
    n_short_skipped = 0
    n_long = n_short = n_sum = 0
    short_groups = {}
    for rec in recs:
        if allowed is not None and not rec['is_article'] and rec.get('text'):
            if (rec.get('handle') or '').lower() not in allowed:
                n_short_skipped += 1
                continue
        has_text = bool(rec.get('text'))
        if not has_text:
            d = os.path.join(OUT, '_仅摘要', '长文' if rec['is_article'] else '短推', ymd(rec))
            os.makedirs(d, exist_ok=True)
            name = f"{rec['id']}__{rec.get('handle') or 'unknown'}__{slug(rec.get('title') or rec.get('summary'))}.md"
            open(os.path.join(d, name), 'w', encoding='utf-8').write(entry_md(rec))
            n_sum += 1
        elif rec['is_article']:
            d = os.path.join(OUT, '长文', ymd(rec))
            os.makedirs(d, exist_ok=True)
            name = f"{rec['id']}__{rec.get('handle') or 'unknown'}__{slug(rec.get('title') or rec['text'][:40])}.md"
            open(os.path.join(d, name), 'w', encoding='utf-8').write(entry_md(rec))
            n_long += 1
        else:
            key = (rec.get('handle') or 'unknown', ymd(rec))
            short_groups.setdefault(key, []).append(rec)
            n_short += 1

    for (handle, month), items in sorted(short_groups.items()):
        d = os.path.join(OUT, '短推', handle)
        os.makedirs(d, exist_ok=True)
        items.sort(key=lambda x: (x.get('created_ts') or 0))
        lines = [f'# @{handle} · {month} 短推合集', '',
                 f'共 {len(items)} 条。按时间正序，每条含原帖链接与数据。', '']
        for it in items:
            lines.append(f"## {bj(it.get('created_ts'))}")
            lines.append(f"- 链接：{it.get('url')}")
            if it.get('likes') is not None:
                lines.append(f"- 数据：赞 {it.get('likes')} / 回 {it.get('replies')} / 阅 {it.get('views')} / 藏 {it.get('bookmarks')}")
            lines.append('')
            lines.append(it['text'])
            lines.append('')
        open(os.path.join(d, f'{month}.md'), 'w', encoding='utf-8').write('\n'.join(lines))

    write_index(recs)
    write_readme(recs, n_long, n_short, n_sum)
    return n_long, n_short, n_sum, n_short_skipped


def write_index(recs):
    cols = ['id', '类型', '作者', '发布时间', '标题/开头', '赞', '阅', '藏', '来源', '链接']
    with open(os.path.join(OUT, '索引.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in recs:
            w.writerow([
                r['id'],
                '长文' if r['is_article'] else '短推',
                r.get('handle') or '',
                bj(r.get('created_ts')),
                (r.get('title') or (r.get('text') or r.get('summary') or '')[:40]).replace('\n', ' '),
                r.get('likes') or '', r.get('views') or '', r.get('bookmarks') or '',
                ('仅摘要' if not r.get('text') else r.get('source', '')),
                r.get('url') or '',
            ])

    by_handle = {}
    for r in recs:
        by_handle.setdefault(r.get('handle') or 'unknown', []).append(r)
    lines = ['# X 参考库索引', '',
             f'更新于 {datetime.now(BJ).strftime("%Y-%m-%d %H:%M")}（北京时间） · 共 {len(recs)} 条 · 作者 {len(by_handle)} 位', '',
             '## 按作者', '']
    for h, items in sorted(by_handle.items(), key=lambda kv: -len(kv[1])):
        longs = sum(1 for x in items if x['is_article'] and x.get('text'))
        shorts = sum(1 for x in items if not x['is_article'] and x.get('text'))
        sums = sum(1 for x in items if not x.get('text'))
        lines.append(f'- **@{h}** 共 {len(items)} 条（长文 {longs} / 短推 {shorts} / 仅摘要 {sums}）')
    lines += ['', '## 最新 30 条', '']
    for r in recs[:30]:
        tag = '长文' if r['is_article'] else '短推'
        label = (r.get('title') or (r.get('text') or r.get('summary') or '').replace('\n', ' ')[:34])
        lines.append(f"- {bj(r.get('created_ts'))} · @{r.get('handle')} · {tag} · {label}")
    open(os.path.join(OUT, '索引.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


def write_readme(recs, n_long, n_short, n_sum):
    txt = f"""# X 参考库

本机所有抓到过的 X（推特）原文{f'，不含作者本人（@{SELF_HANDLE}）的内容' if SELF_HANDLE else ''}。

最后更新：{datetime.now(BJ).strftime('%Y-%m-%d %H:%M')}（北京时间）

## 里面有什么

> ⚠️ 如果这个目录出现在 Obsidian 的 `_inbox/X/参考库`，那是本机 `~/x-reference` 的**单向镜像**。
> 在这里改任何文件都会被下一次同步覆盖（多余的会被删掉）。要改内容，改本机库再重跑同步。

| 目录 | 内容 | 条数 |
|---|---|---|
| `长文/` | X Article 长文全文，一条一个文件 | {n_long} |
| `短推/` | 短推，按「账号/月份」合成一篇，方便通读 | {n_short} |
| `_仅摘要/` | 只抓到榜单标题与摘要、**原文没抓过**的，留着当线索 | {n_sum} |
| `索引.csv` | 全部条目的表格（可用 Excel/表格软件打开筛选） | {len(recs)} |
| `索引.md` | 按作者汇总 + 最新 30 条 | 同上 |
| `_store.jsonl` | 主库，一行一条，按推文 id 去重。**不要手改**，改了重跑会被覆盖 | 同上 |

## 怎么维护

```bash
python3 ~/.hermes/scripts/build_x_library.py --scan   # 只看本机有哪些来源、多少条
python3 ~/.hermes/scripts/build_x_library.py          # 增量更新（幂等，可反复跑）
```

数据来源：`~/.hermes/x-radar/` 下的 article_*.txt、wealth_*.txt、watch_*.json、search_*.json、
articles_history.jsonl、snapshot_*.json。原文件不动，只读。

新增抓取（每天 07:50 的对标账号监控、每天 06:50 的榜单）跑完后，再执行一次本脚本即可把新内容并入。
"""
    open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write(txt)


def scan():
    meta = load_meta()
    structured = load_structured()
    raw = load_raw_texts()
    print(f'榜单历史/快照元数据      : {len(meta)} 条')
    print(f'监控/搜索结构化条目      : {len(structured)} 条')
    print(f'独立正文文件(article/wealth): {len(raw)} 条')
    print(f'三者去重合计             : {len(set(meta) | set(structured) | set(raw))} 条')
    both = set(structured) & set(raw)
    print(f'正文文件与结构化重复     : {len(both)} 条（会按 id 合并）')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--no-live', action='store_true', help='缺元数据时不现查 fxtwitter')
    ap.add_argument('--current-only', action='store_true',
                    help='短推目录只保留当前监控名单内的账号（长文历史全量不动）')
    args = ap.parse_args()
    if args.scan:
        scan()
    else:
        recs = build_store(live=not args.no_live)
        save_store(recs)
        a, b, c, skipped = render(recs, current_only=args.current_only)
        print(f'OK 长文 {a} 篇 · 短推 {b} 条 · 仅摘要 {c} 条 → {OUT}')
        if args.current_only:
            print(f'（--current-only 已开：{skipped} 条名单外账号的短推未渲染，主库 _store.jsonl 仍保留）')
