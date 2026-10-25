#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X 选题雷达 - X 长文正文抓取助手 (fxtwitter 免费镜像通道)

用法:
  python3 x_radar_fetch.py <status_url_or_id> [<handle>]

参数:
  status_url_or_id : x.com/<handle>/status/<id> 完整链接, 或纯 tweet id
  handle           : 可选, 作者 @handle (解析用; status id 足够时可不传)

输出:
  成功 → stdout 打印全文(纯文本) + 写 ~/.hermes/x-radar/article_<id>.txt
  失败 → stderr 打印错误, exit 1 (不 push 噪音)

数据来源: api.fxtwitter.com/<handle>/status/<id>
"""

import sys, os, re, json, urllib.request

WORK = os.path.expanduser(os.environ.get('XRADAR_HOME') or '~/.hermes/x-radar')
os.makedirs(WORK, exist_ok=True)


def parse_args(argv):
    if len(argv) < 2:
        print("usage: x_radar_fetch.py <status_url_or_id> [handle]", file=sys.stderr)
        sys.exit(2)
    raw = argv[1]
    handle = argv[2] if len(argv) > 2 else None
    m = re.search(r'status/(\d+)', raw)
    tid = m.group(1) if m else raw.strip()
    if handle is None:
        m2 = re.search(r'x\.com/([A-Za-z0-9_]+)/status', raw)
        handle = m2.group(1) if m2 else None
    return tid, handle


def fetch(tid, handle):
    # 有 handle 走 /<handle>/status/<id>；只有 id 时走 /2/status/<id>（不需要知道作者是谁）
    if handle:
        url = f"https://api.fxtwitter.com/{handle}/status/{tid}"
    else:
        url = f"https://api.fxtwitter.com/2/status/{tid}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode('utf-8', errors='replace'))
    # 坑：/2/status/<id> 顶层键是 status，/<handle>/status/<id> 是 tweet，两个都要认
    tweet = data.get('tweet') or data.get('status') or {}
    article = tweet.get('article') or {}
    blocks = article.get('content', {}).get('blocks') or []
    if blocks:
        return '\n\n'.join(b.get('text', '') for b in blocks if b.get('text'))
    # 无 article blocks → 退而取 tweet 自带文本
    text = (tweet.get('text') or '').strip()
    if text:
        return text
    return None


def main():
    tid, handle = parse_args(sys.argv)
    try:
        text = fetch(tid, handle)
    except Exception as e:
        print(f"ERROR fetch {tid}: {e}", file=sys.stderr)
        sys.exit(1)
    if not text:
        print(f"ERROR: no long-article body for {tid} (可能不是长文)", file=sys.stderr)
        sys.exit(1)
    out = os.path.join(WORK, f'article_{tid}.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(out)


if __name__ == '__main__':
    main()
