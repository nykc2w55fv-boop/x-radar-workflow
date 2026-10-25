# AGENTS.md

给 Codex、Claude Code 以及其它能执行 shell 的编码 agent 读的约定。人不用看这一份，去看 README.md。

## 这是什么

一套六环节的 X 内容抓取管道。每个环节是一个独立脚本，产物是文件，环节之间靠文件传递，不靠标准输出。

## 数据目录

所有产物在 `${XRADAR_HOME:-~/.hermes/x-radar}/`，参考库在 `${XRADAR_LIBRARY:-~/x-reference}/`。

不要把这些产物写进仓库目录。`.gitignore` 已经拦了常见模式，但新增脚本时请自己守这条规矩。

## 环节与调用方式

按需调用，不要无脑全跑。用户说「找今天能写什么」时，通常是 1→2→3 并行，然后 6 归集。

| 环节 | 命令 | 何时用 | 耗时量级 | 前置条件 |
|---|---|---|---|---|
| 1 榜单 | `bash scripts/x_radar_scrape.sh` | 要泛热点 | 3 到 10 秒 | 需要 Chrome/Chromium |
| 2 精选 | `python3 scripts/aihot_fetch.py` | 要 AI 领域已筛过的 | 2 到 5 秒 | 无 |
| 3 对标账号 | `python3 scripts/x_watch_fetch.py --hours 36` | 要特定账号动态 | 每秒约 0.4 个账号 | 名单文件存在 |
| 4 关键词 | `python3 scripts/x_search_fetch.py` | 要按话题找 | 每查询 2 到 10 秒 | 有 `TWITTERAPI_IO_KEY`，没有就跳过 |
| 5 长文全文 | `python3 scripts/x_radar_fetch.py <url>` | 需要某篇全文 | 2 到 15 秒 | 无 |
| 6 归集 | `python3 scripts/build_x_library.py` | 抓完一批后 | 1 到 5 秒 | 前面至少有一环产出过 |

串联版本（定时任务用）：`bash scripts/x_watch_all.sh`，内部跑 3 和 4，任意一个失败都不影响另一个，整体 exit 0。

## 关键规则

**不要为了让脚本「不报错」而吞掉真实错误。** 这些脚本有意在缺配置时静默跳过（比如没有 key），那是设计，不是 bug；但如果某个环节本该有产出却产出了零条，要如实告诉用户，别编。

**长文正文只认两处来源。** `article_<id>.txt`（fxtwitter 抓的）和 `wealth_<id>.txt`（榜单筛出来的）。归集脚本只认这两个前缀，改了文件名就不入库。

**去重靠 id，不靠标题。** 水位文件 `*_seen.json` 不能手动清空，清了会重复推送。

**改抓取选择器前先看 docs/FAQ.md。** 上游页面结构改过好几次，历史教训都记在那里。

## 修改代码时

- 只用标准库，除非有强理由。这个项目对第三方依赖是负资产。
- 任何新增的绝对路径都写成 `os.environ.get('XXX') or 默认值` 的形式。
- 密钥只从环境变量或 `~/.hermes/.env` 读，**永远不要写死在文件里，也不要打印到日志**。
- 时间统一按北京时间（UTC+8）显示，产物文件名也用北京日期。

## 测试

改完之后至少跑一遍：

```bash
python3 -m py_compile scripts/*.py
bash -n scripts/x_radar_scrape.sh
python3 scripts/x_watch_fetch.py --list     # 只读名单，不发网络请求
```

需要端到端验证时，把 `XRADAR_HOME` 指到一个临时目录，别污染真实数据：

```bash
XRADAR_HOME=/tmp/xr-test python3 scripts/x_watch_fetch.py --hours 6
```
