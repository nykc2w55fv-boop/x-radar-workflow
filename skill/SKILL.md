---
name: x-radar-workflow
description: X（推特）选题雷达。抓热门长文榜、AI 精选、对标账号动态、关键词命中与长文全文，归集成本地可检索参考库。触发词：跑选题雷达、今天 X 上有什么可写的、抓一下对标账号、建 X 参考库。
---

# X 选题雷达

## 什么时候用

- 用户问「今天 X 上有什么值得写的」→ 跑环节 1、2、3，汇总后按 AI 相关度筛，给 3 到 5 个选题角度
- 用户点名某个账号或链接 → 环节 5 抓全文
- 用户说「补库 / 归集」→ 环节 6
- 想长期跟踪 → `scripts/x_watch_all.sh` 挂定时任务，每天一次

## 环境准备（只做一次）

```bash
bash install.sh
```

数据在 `${XRADAR_HOME:-~/.hermes/x-radar}/`，参考库在 `${XRADAR_LIBRARY:-~/x-reference}/`。

## 六步流程

### 1. 榜单（免费）

```bash
bash scripts/x_radar_scrape.sh
```

产物 `snapshot_<北京日期>.json`，同时追加到 `articles_history.jsonl`。脚本自己会打印 `AI_candidates=N/total=M`，直接看这个数字判断今天值不值得往下做。

需要 Chrome。找不到浏览器时脚本会明确报错，不会静默产出空文件。

### 2. 精选（免费）

```bash
python3 scripts/aihot_fetch.py
```

产物 `aihot_<日期>.md`，去重后的历史在 `aihot_history.jsonl`。

### 3. 对标账号（免费）

```bash
python3 scripts/x_watch_fetch.py --hours 36            # 常用
python3 scripts/x_watch_fetch.py --count 20 --min-likes 20   # 要更多更精
python3 scripts/x_watch_fetch.py --list                # 只看名单和上次状态
```

名单在 `watch_accounts.txt`，`[分类]` 行分组。产物 `watch_<日期>.json` 和 `.md`。

单个账号失败不影响整体，失败记录在 md 末尾「抓取异常」里。**报错超过名单三分之一时要看 FAQ**，通常是上游在抖或者本机网络问题。

### 4. 关键词（可选，花钱）

```bash
python3 scripts/x_search_fetch.py --probe    # 先验 key 和余额，最便宜
python3 scripts/x_search_fetch.py            # 跑全部查询
python3 scripts/x_search_fetch.py --query '"一人公司" lang:zh'
```

没有 `TWITTERAPI_IO_KEY` 时打印 `SKIP` 并 exit 0，这是设计。不要为了让它「跑起来」去编一个 key。

### 5. 长文全文

```bash
python3 scripts/x_radar_fetch.py https://x.com/<handle>/status/<id>
```

正文打到标准输出，同时写 `article_<id>.txt`。

### 6. 归集建库

```bash
python3 scripts/build_x_library.py
```

扫描上面所有产物，去重后写进 `~/x-reference/`：长文按 `年-月` 分目录，短推按账号合月，生成 `索引.csv`、`索引.md`、`README.md`。

## 交付给用户时

- 只给筛过的结果，不要贴原始 JSON
- 每条带链接、点赞数、作者，用户要判断值不值得点开
- 明确区分「榜单捞到的」和「你名单里的人发的」，两者可信度不一样
- 抓取失败的环节要如实说，别用「大概」「应该」糊过去

## 硬性规则

- 不登录、不用 Cookie、不碰用户自己的 X 账号，全部走公开只读接口
- 密钥只从环境变量或 `~/.hermes/.env` 读，任何时候都不要打印出来
- 产物落在数据目录，**不进代码仓库**
- 时间一律北京时间
- 改代码只用标准库，不引入第三方依赖
