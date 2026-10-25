# 踩坑记录

都是实际撞过的，按撞到的频率排。

## 1. 关键词搜索：fxtwitter 的搜索接口是 404

`api.fxtwitter.com/2/search` 不管怎么传参都返回 404。所以「按关键词找话题」这一环**没有免费通道**，只能用 twitterapi.io 这类付费接口。别浪费时间试免费方案，试过了。

对标账号和长文全文不受影响，那两个用 fxtwitter 是好的。

## 2. twitterapi.io 免费档有 QPS 限制

表现是跑几条查询之后开始回 429，日志里写着 `For free-tier users...`。脚本内置了 4 次重试加退避，但如果你查询条数多，还是会漏。

三个办法：
- 查询之间本来就有间隔，别把 6 条查询拆成 6 个并发任务
- 查询里带 `min_faves:50`，返回条数少了，被限流的概率也低
- 真跑大批量就升级套餐

先跑 `--probe`，它只发一次请求，最省钱，能验 key 是否有效、余额是否够。

## 3. 长文全文的返回结构有两个坑

`/2/status/<id>` 的顶层键是 `status`；`/<handle>/status/<id>` 的顶层键是 `tweet`。两个都要认，只认一个会拿到空正文。

正文在 `tweet.article.content.blocks` 里，是一个块数组，要按顺序拼 `text` 字段。有些推文没有 article，退回 `tweet.text`。

## 4. 榜单页面结构会变

`x_radar_scrape.sh` 靠正则解析 HTML。上游改版时正则全失效，表现是「跑成功但 0 条」。

判断方法：看 `dom_<日期>.html` 是不是有内容。有内容但解析出 0 条 = 正则过期；文件本身是空的 = 浏览器没起来。

修法：打开 html 找一张卡片的真实结构，改 `card_re` 那条正则。互动数据的图标顺序也在脚本里写死了（`chart-column`、`heart`、`message-circle`、`bookmark`），改版时一起核对。

## 5. 无头浏览器找不到

脚本按这个顺序找：`$CHROME_BIN` → Playwright 缓存里最新的 chromium → 系统 `google-chrome` / `chromium` / `chromium-browser`。

服务器上最常见的失败是装了个 `chromium` 但它是 snap 包，路径在 `/snap/bin` 且行为不一样。建议直接 `python3 -m playwright install chromium`，省事。

## 6. 定时任务被一次网络故障搞成红叉

`x_watch_all.sh` 的设计是永远 exit 0，两个通道互相隔离。这是有意的：定时任务红了会天天给你发报警，比漏一天更烦人。

代价是失败被静默。所以要么每天看一眼产物文件的修改时间，要么在外面套一层检查：

```bash
find ~/.hermes/x-radar -name "watch_$(TZ=Asia/Shanghai date +%F).json" -mmin -600 | grep -q . || echo "今天没抓到"
```

## 7. 抓三个月后库变得很慢

`_store.jsonl` 是主库，一行一条。到十万条量级时 `build_x_library.py` 会明显变慢，因为它每次全量重读。

在那之前不用管。真要优化，把 `_store.jsonl` 按年份切开，改 `load_store` 只读近两年。

## 8. Obsidian 镜像把整个 vault 都提交了

`sync_x_library_to_obsidian.sh` 只 `git add` 参考库那一个子目录，不碰你 vault 里的私人笔记。如果你改了脚本，务必保留这个约束。

另外它用 `--delete` 单向同步：本地库删了，镜像也删。**不要反向改镜像里的文件**，下次同步就没了。

---

## 附：给 Grok bot 或其它 agent 的提示词

```
你有一个本地工具目录 x-radar-workflow，负责从 X 抓取选题素材。

工作流程：
1. 先跑 bash scripts/x_radar_scrape.sh 看泛热点，它会打印 AI_candidates=N/total=M
2. 同时跑 python3 scripts/aihot_fetch.py 拿 AI 领域精选
3. 跑 python3 scripts/x_watch_fetch.py --hours 36 拿监控账号的新动态
4. 有 TWITTERAPI_IO_KEY 就跑 python3 scripts/x_search_fetch.py，没有就跳过，不要报错
5. 所有产物在 ~/.hermes/x-radar/，归集用 python3 scripts/build_x_library.py
6. 需要某篇长文全文时用 python3 scripts/x_radar_fetch.py <推文链接>

规则：
- 产物是文件，读文件不要读标准输出
- 失败要如实报告，不要为了「跑通」编造结果
- 不要打印任何 API Key
- 时间按北京时间
- 汇总时区分「榜单捞的」和「名单里的人发的」
```
