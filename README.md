# X 选题雷达 · x-radar-workflow

把 X（推特）上「值得写的内容」自动捞出来，变成你本地可检索的参考库。

给中文创作者、研究员、一人公司用的。六个环节各自独立，缺哪个都不影响其它环节跑：

| 环节 | 干什么 | 通道 | 要钱吗 |
|---|---|---|---|
| 1. 榜单 | 抓热门长文榜全部条目 | 无头浏览器渲染 | 免费 |
| 2. 精选 | 抓 AI 领域每日精选 | 公开只读接口 | 免费 |
| 3. 对标账号 | 盯住你的名单，抓它们的新帖和新长文 | 公开只读接口 | 免费 |
| 4. 关键词 | 按高级搜索语法找话题 | twitterapi.io | 按条计费，可选 |
| 5. 长文全文 | 单篇长文抓全文（转 Markdown） | 公开只读接口 | 免费 |
| 6. 归集建库 | 去重、分目录、生成索引 | 本地 | 免费 |

最后你会得到一个 `~/x-reference/` 目录：长文按年月分开，短推按账号按月份合成一篇，带 csv 和 md 两套索引。可以直接丢进 Obsidian、思源、或者任何 grep 得动的编辑器。

> **English summary**: A six-stage X/Twitter content radar. Scrapes trending long-form rankings, curated AI picks, a watchlist of accounts, keyword searches and full article text, then deduplicates everything into a local Markdown library with indexes. Pure Python standard library (plus headless Chrome for one stage). Works with Codex, Claude Code, Hermes and any agent that can run shell commands. Free for non-commercial use; commercial use requires a paid license.

---

## 为什么要这么拆

大多数「X 内容抓取」方案死在两个地方：一是把抓取和判断揉在一个大脚本里，接口一改就全废；二是所有数据堆一个文件，抓三个月就再也搜不动。

所以这里故意做成管道：每一环只干一件事，产物是文件，中间断了不影响前面的成果。你甚至可以把某一环换成自己写的，只要产物格式对得上。

## 作者环境实测（跑通后的真实数字，不是估算）

| 环节 | 命令 | 结果 |
|---|---|---|
| 榜单 | `x_radar_scrape.sh` | 2.5 秒，20 篇，其中 9 条 AI 相关候选 |
| 精选 | `aihot_fetch.py` | 4 条，落盘 3.9 KB |
| 对标账号 18 个 | `x_watch_fetch.py` | 46 秒，新增 16 条，累计 53 条，异常 0 |
| 关键词 5 条查询 | `x_search_fetch.py` | 67 条，异常 0，最高 1287 赞 |
| 长文全文 | `x_radar_fetch.py` | 单篇 27075 字节，最长一篇 5224 字 |
| 归集建库 | `build_x_library.py` | 入库 499 条，其中长文 368 篇 |

你的数字会跟自己的名单长度、网络情况有关，量级大致如此。

## 三条命令开始

```bash
git clone https://github.com/nykc2w55fv-boop/x-radar-workflow.git
cd x-radar-workflow
bash install.sh
```

`install.sh` 会建好数据目录、从模板生成两份配置文件、生成密钥文件（权限 600），最后跑一次只读的冒烟测试。它幂等，重复执行不会覆盖你已经改过的配置。

然后改名单，跑第一轮：

```bash
$EDITOR ~/.hermes/x-radar/watch_accounts.txt     # 换成你要盯的账号
python3 scripts/x_watch_fetch.py --hours 36      # 抓最近 36 小时
python3 scripts/build_x_library.py               # 归集成本地库
```

打开 `~/x-reference/索引.md` 看看。

## 依赖

只有一个可选依赖：**无头 Chrome / Chromium**，只有「榜单」那一环需要（因为它要等页面的 JavaScript 跑完）。

- 已有 Chrome：什么都不用装，脚本自己找
- 没有：`python3 -m playwright install chromium` 或者 `sudo apt install chromium`
- 装在奇怪的位置：`export CHROME_BIN=/path/to/chrome`

其余五个环节纯 Python 标准库，**不需要 pip install 任何东西**。这是故意的：依赖越少，别人 fork 之后越不容易卡在装环境上。

Python 3.8 以上。

## 目录结构

```
x-radar-workflow/
├── install.sh                  一键准备环境（幂等）
├── scripts/
│   ├── x_radar_scrape.sh       环节1 榜单（无头浏览器）
│   ├── aihot_fetch.py          环节2 精选
│   ├── x_watch_fetch.py        环节3 对标账号
│   ├── x_search_fetch.py       环节4 关键词（可选，需 key）
│   ├── x_radar_fetch.py        环节5 单篇长文全文
│   ├── build_x_library.py      环节6 归集建库
│   ├── x_watch_all.sh          把 3+4 串起来，给定时任务用
│   └── sync_x_library_to_obsidian.sh   可选：镜像到 Obsidian
├── config/
│   ├── watch_accounts.example.txt     监控名单模板
│   └── watch_queries.example.txt      关键词模板
├── skill/SKILL.md              给 agent 用的技能说明
├── AGENTS.md                   给 Codex / Claude Code 的项目约定
├── .env.example                密钥模板
└── docs/FAQ.md                 踩坑记录
```

数据全部落在 `${XRADAR_HOME:-~/.hermes/x-radar}/`，代码目录不放任何抓取产物。

## 配置

三种方式，优先级从高到低：

1. 环境变量：`XRADAR_HOME`（数据目录）、`XRADAR_LIBRARY`（库目录）、`XRADAR_ENV`（密钥文件位置）、`CHROME_BIN`（浏览器）
2. 密钥文件 `~/.hermes/.env`：`TWITTERAPI_IO_KEY=xxx`
3. 默认值：数据在 `~/.hermes/x-radar/`，库在 `~/x-reference/`

**唯一要花钱的地方**是关键词通道。去 twitterapi.io 注册拿 key，填进 `.env`。不填也行，那一环会打印 `SKIP` 然后正常退出，不会让定时任务报错。

省钱建议：查询里带 `min_faves:50`，一条查询返回多少条就按多少条计费，门槛是最有效的旋钮。先 `--probe` 验 key，再跑全量。

## 接到 agent 上

这套东西本来就是给 agent 用的，人手动敲只是调试。

**Codex / Claude Code / 通用 coding agent**：把仓库放进工作目录，`AGENTS.md` 会被自动读取，里面写了每个环节什么时候该跑、产物在哪。

**Hermes**：把 `skill/SKILL.md` 放进 skills 目录（或者 `~/.hermes/skills/content/x-topic-radar/`），说一句「跑选题雷达」就会按流程走。

**Grok bot / 其它能执行命令的 bot**：`docs/FAQ.md` 末尾有一段可直接粘的提示词，写明六步顺序和每步的判定条件。

三个入口共用同一批脚本，不维护三套代码。

## 设计上的几个取舍

**产物一律是文件，不是返回值。** 因为下一步通常是 agent 来读，文件比标准输出可靠，也方便你事后翻。

**去重水位单独存。** `*_seen.json` 只记 id，不记内容，跑半年也就几百 KB。

**失败永远 exit 0（定时任务用）。** `x_watch_all.sh` 里两个通道互相隔离，一个挂了另一个照跑，整体不报错。代价是你得看日志才知道哪一环空了，所以每天看一眼产物文件的修改时间。

**不抓关注列表、不登录、不碰你的账号。** 全部走公开只读接口，不涉及任何 Cookie 和登录态。

## 协议

代码用 **PolyForm Noncommercial License 1.0.0**：

- ✅ 个人学习、研究、非营利用途：免费用，可以改，可以 fork
- ❌ 公司内部使用、SaaS、付费课程、代运营、外包交付：需要商业授权

商用授权见 [COMMERCIAL.md](COMMERCIAL.md)。

---

如果这套流程帮你省下了搭管道的时间，欢迎在 Issues 里说说你把它改成了什么样子。
