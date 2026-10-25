#!/usr/bin/env python3
"""AIHOT 素材抓取 —— 为 08:00「X选题雷达·每日AI分析」提供第二信源。

数据源：https://aihot.news/api/v1/items （匿名只读，无需 API Key）
产物：
  ~/.hermes/x-radar/aihot_<YYYY-MM-DD>.md    当日精选素材（供 agent read_file）
  ~/.hermes/x-radar/aihot_history.jsonl      累计历史（幂等去重，供选题池积累）

过滤：selected=true、score >= MIN_SCORE、发布时间在最近 LOOKBACK_H 小时内。
输出上限 MAX_ITEMS 条，按评分倒序。
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://aihot.news/api/v1/items?limit=60"
WORK = os.path.expanduser(os.environ.get('XRADAR_HOME') or '~/.hermes/x-radar')
MIN_SCORE = int(os.environ.get("AIHOT_MIN_SCORE", "70"))
LOOKBACK_H = int(os.environ.get("AIHOT_LOOKBACK_H", "30"))
MAX_ITEMS = int(os.environ.get("AIHOT_MAX_ITEMS", "15"))

CATEGORY_ZH = {
    "ai-models": "模型",
    "industry": "行业动态",
    "product": "产品发布",
    "model": "模型",
    "research": "研究论文",
    "tutorial": "教程",
    "opinion": "观点",
    "tool": "工具",
}


def fetch():
    req = urllib.request.Request(
        API,
        headers={"User-Agent": "hermes-aihot-fetcher/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    os.makedirs(WORK, exist_ok=True)
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_H)

    try:
        data = fetch()
    except Exception as e:
        print(f"ERROR: AIHOT API 拉取失败: {e}", file=sys.stderr)
        return 1

    picked = []
    for it in data.get("items", []):
        try:
            if not it.get("selected"):
                continue
            if int(it.get("score") or 0) < MIN_SCORE:
                continue
            if parse_dt(it["publishedAt"]) < cutoff:
                continue
        except Exception:
            continue
        picked.append(it)

    picked.sort(key=lambda x: (-int(x.get("score") or 0), x.get("publishedAt", "")))
    picked = picked[:MAX_ITEMS]

    md_path = os.path.join(WORK, f"aihot_{today}.md")
    if not picked:
        print(f"[SILENT] AIHOT: {today} 无评分>={MIN_SCORE} 的新素材")
        # 不写空文件，避免下游误读
        return 0

    lines = [
        f"# AIHOT 今日精选 · {today}",
        "",
        f"来源：aihot.news（卡兹克 AI 资讯站，已 AI 初筛+双重打分）。"
        f"抓取时间 {datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M')} 北京时间，"
        f"共 {len(picked)} 条，评分阈值 {MIN_SCORE}，回看 {LOOKBACK_H} 小时。",
        "",
        "用法：作为选题雷达的第二信源，和 X 榜单交叉比对。标题党/纯融资消息优先跳过，"
        "优先用「模型发布/产品能力/研究结论/行业规则变化」这类能落到读者利益上的。",
        "",
    ]
    for i, it in enumerate(picked, 1):
        score = it.get("score")
        cat = CATEGORY_ZH.get(it.get("category") or "", it.get("category") or "其他")
        src = (it.get("source") or {}).get("name", "未知来源")
        links = it.get("links") or {}
        pub = parse_dt(it["publishedAt"]).astimezone(timezone(timedelta(hours=8)))
        lines += [
            f"## {i}. {it.get('title', '').strip()}",
            f"- 评分 {score} · {cat} · {src} · {pub.strftime('%m-%d %H:%M')} 北京时间",
            f"- 摘要：{it.get('summary', '').strip()}",
        ]
        reason = (it.get("reason") or "").strip()
        if reason:
            lines.append(f"- 推荐理由：{reason}")
        if links.get("original"):
            lines.append(f"- 原文：{links['original']}")
        if links.get("aihot"):
            lines.append(f"- 站内：{links['aihot']}")
        lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 历史追加（按 id 去重）
    hist_path = os.path.join(WORK, "aihot_history.jsonl")
    seen = set()
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                for ln in f:
                    try:
                        seen.add(json.loads(ln).get("id"))
                    except Exception:
                        pass
        except Exception:
            pass
    with open(hist_path, "a", encoding="utf-8") as f:
        for it in picked:
            if it.get("id") in seen:
                continue
            f.write(json.dumps({
                "id": it.get("id"),
                "date": today,
                "title": it.get("title"),
                "score": it.get("score"),
                "category": it.get("category"),
                "source": (it.get("source") or {}).get("name"),
                "url": (it.get("links") or {}).get("original"),
                "summary": it.get("summary"),
            }, ensure_ascii=False) + "\n")

    print(f"OK: {len(picked)} 条 → {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
