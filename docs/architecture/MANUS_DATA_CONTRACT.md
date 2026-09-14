# Manus 信源数据契约（MANUS_DATA_CONTRACT）

> 版本：2026-08-17 初版。契约变更必须先改本文件与 `tests/pipeline/test_manus_contract.py`，再改生产代码。
> 校验实现：`scripts/manus_source/contracts.py`（离线单测：`python -m unittest tests.pipeline.test_manus_contract -v`）

## 2026-09-14 统一发布契约

### 逐篇保留与部分覆盖

时间统一口径：窗口与展示使用北京时间。腾讯、网易、微信、机器之心、白鲸等已确认中国媒体入口返回未标时区的绝对日期时间时，解析为Asia/Shanghai，不因缺少UTC+8拒绝。带Z或其他偏移的时间按同一时刻转换为北京时间，不直接改写时区标签。只有相对时间或日期仍不伪造分钟和秒；这些是时间精度问题，与时区缺失不同。浏览器查看者所在时区不得改变新闻日期。

用户确认窗口仍为09:30至09:30。发现审计新增 `source_status=partial`，必须带说明并保留至少一篇合法文章；`complete` 表示完成窗口扫描，`failed` 表示未获得可用文章且扫描失败。文章仍须通过来源三元组、精确时间、窗口和正文门禁，不能把覆盖不完整当作文章不合法。

Manus 可在 `assistant_message.content` 中逐行发送 `AIHOT_ARTICLE {完整文章JSON}`。仅解析此明确格式，不把“找到几篇”等叙述、用户消息或工具输出转换为文章。每条先校验再写私有 checkpoint 文件，同URL去重。轮询先接收结果，再检查已观察到的费用；停止成功后进行一次有页数上限的只读结果回收。保留文章的同时继续记录止损异常，使费用熔断仍生效。checkpoint 不证明完整覆盖，默认回收为partial。

日常全流程将partial来源的合格正文交给共享模型处理；旧feed统计中 failedAccounts 为未完整覆盖来源数（含partial），不得当作全部不可用。网页以逐来源collectionStatus为准。缓存的partial结果默认保留，不因模板更新自动付费重试。

后续投资人验收增加私有 `inputs/company-evidence.json`：只含审核通过文章的id、url和采集证据，供公司抽取使用。该文件不得提交或随前端发布。公司公开记录区分 `latestReportAt` 和 `profileUpdatedAt`，不以模型重跑时刻冒充报道时间。相关性引文先验证连续原文，再截取80字用于展示；验证不能只检查截断后的片段。

完整入口采用[统一新闻链路](UNIFIED_NEWS_PIPELINE.md)。默认窗口现为09:30至09:30，`ten-am` 名称保留兼容。逐来源发现和正文仍必须通过时间、身份及结构校验。统一 news 阶段允许部分来源失败或合法零篇，并生成新 Manus feed 与共享快照；不套用旧独立 feed 的全来源发布门禁。所有来源不可用或共享模型加工未完成则禁止发布。快照与 feed 的 `collectionStatus` 记录逐来源状态、文章数量和窗口，网页列出缺失来源；禁止从旧正式 feed 补入当前新闻。

## 2026-09-09 十点窗口契约（历史背景）

- 2026-09-10：逐来源本地缓存可附加 `sourceIdentity: {account_name, platform, home_url}`，由 runner 写入，不要求 Manus 生成，不进入合并 feed。缓存入口改变或旧零条结果无法核实入口时，返回失败审计 `source_config_unverified` 并保留费用锁，不能冒充当前配置通过。

- 该版统一入口使用北京时间前一日 10:00（含）至 date 当日 10:00（不含）的固定窗口。
- 窗口发现结果为 `schema_version=3`，本地附加 `collectionWindow: {start, end, timezone}`，每篇 complete 文章新增 `published_at`（含时区 ISO8601）。`published_date` 必须等于该时间在北京时间的日期，允许跨两个自然日；时间必须处于窗口内。未知时间不能用日期推算。
- 旧自然日发现结果 v2 继续可用。v2 保留“文章日期等于 target_date”的规则；不与 v3 三组混用。十点原始文件在 `work/manus/ten-am/<date>/raw/`。
- 正文批次的 target_date 代表运行批次；窗口模式逐 URL 与发现结果的实际 published_date 校验，因此前一天与当日的正文均可通过，不能替换为批次日期。
- feed 当前生成 schemaVersion=2，并继续读取历史 schemaVersion=1。v2 新增真实承载页来源类型；collectionWindow 仍为可选，窗口 feed 的 publishedPrecision 为 datetime，publishedAt 为发现阶段核实的真实时间。
- 快照顶层新增 collectionWindow，daily.range 新增 startAt/endAt；上游新增入库和日报均按此过滤。历史归档、自然周与融资表的历史范围保留。以下 v2 章节描述旧自然日兼容模式。

## 2026-09-08 运行与发布补充

JSON schema 保持不变。`build_manus_feed.validate_publishable()` 补充发布门槛：存在发现文章或失败账号而发布列表为空时拒绝覆盖；所有账号成功且真实无文章时允许空 feed。融资表存在输入但全部抽取失败（包含预算结束未处理项）时拒绝发布，成功抽取没有公司时允许空表。

正文恢复仅复用成功 URL，后续成功记录优先于历史失败；enrichment 仅复用 complete 缓存，fallback 重试。发现 `--resume` 仅复用同日契约合法且来源全部成功的组。

统一入口先写候选目录，再验证并发布所选阶段产物；失败保留正式数据，运行状态在 `work/runs/`。多目录发布、恢复与边界见 [自动流水线](../operations/AUTOMATED_PIPELINE.md)。原有单阶段 CLI 的输出 schema 与公开 URL 保持不变。

## 总览

| 契约 | 载体 | 生产者 | 校验函数 |
|---|---|---|---|
| 发现结果（schema v2） | `work/manus/<date>/raw/discovery-<group>.json` | Manus 发现任务 | `validate_discovery()` |
| 正文批次 | `work/manus/<date>/raw/content-batch-NN.json` | 本地脚本爬虫（`crawler.py`，trafilatura；可选 Manus 正文任务回退） | `validate_content_batch()` |
| 规范化 feed | `data/manus/current.json` + `data/archive/YYYY-MM-DD.json` | `build_manus_feed.py` | `validate_feed()` |
| 运行状态 | `data/manus/state.json` | `build_manus_feed.py` / 工作流 | 无强校验（运维只读） |

## 1. 发现结果（schema_version=2）

```json
{
  "schema_version": 2,
  "source_group": "group_a",
  "target_date": "2026-08-16",
  "source_audits": [
    {"account_name": "游戏葡萄", "source_status": "complete", "article_count": 2, "note": null},
    {"account_name": "白鲸出海", "source_status": "complete", "article_count": 0, "note": "当天无文章"},
    {"account_name": "ZFinance", "source_status": "failed", "article_count": 0, "note": "失败原因"}
  ],
  "articles": [
    {
      "account_name": "游戏葡萄", "source_platform": "Tencent News",
      "source_home_url": "https://...", "article_url": "https://...",
      "title": "...", "published_date": "2026-08-16", "author": null,
      "extraction_status": "complete", "note": null
    }
  ]
}
```

硬性规则：

- 三组（group_a/b/c）必须全部存在且合法，才允许晋升新一版 `current.json`。
- 单账号 canary 用同一 `validate_discovery()` 校验该账号，产物隔离在 `work/manus[/ten-am]/canary/`。逐来源入口可复用同账号、同窗口、成功且契约合法的结果，再按配置顺序合并并验证三组；它不能直接替代三组生产契约。
- 每个配置账号（`config/manus_sources.json`）恰好一条 `source_audits`；`complete + article_count=0`
  表示“来源成功但当天无文章”，不得与 `failed` 混淆。
- `complete` 文章：账号、URL、标题、日期非空，`published_date` 必须等于 `target_date`。
- `failed` 记录：`article_url/title/published_date/author` 恒为 null，`note` 必填失败原因。
- `article_count` 必须等于该账号 complete 文章数。

## 2. 正文批次

```json
{
  "target_date": "2026-08-16",
  "articles": [
    {
      "account_name": "机器之心", "article_url": "https://...",
      "title": "...", "published_date": "2026-08-16",
      "content_text": "清洗后的可读正文",
      "content_status": "complete", "content_truncated": false, "note": null
    }
  ]
}
```

本地门槛（`validate_content_batch`）：

- `content_status=failed` 或风控/验证码页特征（短文本 + 特征词）→ 失败记录，不进入模型加工。
- 与发现阶段标题不一致（跳转漂移）→ 失败。
- 正文长度 < `MANUS_MIN_CONTENT_CHARS`（默认 100）→ 失败。
- 批次 URL 集合必须与请求清单一一对应（不漏不增）。
- 正文原文只存在于运行时 `work/`（已 gitignore），不入库、不进 Artifact；诊断目录仅含
  URL/状态/长度/哈希/原因。

正文生产者为本地脚本爬虫（`crawler.py`，trafilatura 提取；默认 `MANUS_CONTENT_MODE=script`）：
爬虫在产出记录前已做跳转漂移（final URL/标题）、风控页、正文过短判定，再经本契约统一校验；
标题一致性由爬虫宽松比较（剥离空白 + 双向子串）容忍站点后缀与空格漂移。
回退模式 `MANUS_CONTENT_MODE=manus` 保留 Manus 正文任务路径，产出同一契约。

## 3. 规范化 feed（`data/manus/current.json`，schemaVersion=2）

字段与 `tests/fixtures/manus/current.json` 一致。要点：

- `ok=true` 才可消费；`degraded=true` 表示存在来源级失败（成功文章照常发布）。
- `sourceType` 按实际承载页写为 `wechat`、`media` 或 `direct`；`sourceChannel` 进一步区分 `wechat_original`、`tencent_syndication`、`netease_syndication`、`publisher_site` 和 `media_page`。账号名相同不能作为公众号身份依据。历史 schemaVersion=1 的 `wechat` 条目继续兼容。
- `id` = `manus:` + sha256(账号|日期|归一化标题) 前 16 位（`stable_article_id`）。
- 正文先经过 `screen_news.py` 的 AI 相关性门禁。模型必须返回可在标题或正文中核对的原文证据；无关文章在摘要、标签、公司与融资抽取前排除，失败或超过本轮上限的文章不发布。
- 只有日期时用北京时间 12:00 占位且 `publishedPrecision="date"`，页面不得展示为精确时间。
- `classification` 保存 taxonomy id；渲染时经 `tag_news.to_display()` 转中文。
- `contentSha256` 为正文哈希；**全文绝不进入 feed**。
- stats 自洽：`configuredAccounts = complete + failed`；`publishedArticles = len(items)`；
  `fallbackArticles` = `enrichmentStatus=fallback` 条数；`discovered >= published`。v2 另外记录相关性筛选的输入、保留、排除、失败和待处理数量。
- 空 `items` + `ok=true` 是合法的“当天无文章”，不是故障。

## 4. state.json

```json
{
  "lastRunAt": "...", "targetDate": "...", "promoted": true,
  "failure": null, "taskUrls": {}, "stats": {...},
  "degraded": false, "lastSuccessDate": "2026-08-16"
}
```

不含 API key、不含正文。快照工作流消费时依据 feed 的 `targetDate` 判断新鲜度
（`build_snapshot.py --manus-max-stale-days`，默认 3 天）；`lastSuccessDate` 供运维诊断。

## 版本升级规则

- 发现 schema：升级 `schema_version` 时同步改 Manus structured_output_schema、prompt 输出节、
  `validate_discovery` 与夹具。
- feed schema：升级 `schemaVersion` 时，消费者（`build_snapshot.load_manus_feed`）需同时兼容
  上一版或按日归档副本回退；禁止静默破坏旧归档。


## 2026-09-14：单条隔离与“昨天”收录口径

用户确认单条失败不得阻断整批。相关新闻缺证据、摘要分类未通过时，写入collectionStatus.quarantined及计数，不进入新闻或公司证据输入；公司抽取失败写入articleFailures，已有资料保留。来源、模型阶段整体不可用和跨产物校验失败仍保护旧网页。前端显示隔离数量、原因与原文链接。

绝对时间维持北京时间前一日09:30至当天09:30的固定窗口。原文或对应卡片标注“昨天”时，按采集记录接收时间（北京时间）的前一自然日全天纳入，这是用户授权的日期精度例外，不宣称严格24小时覆盖。published_at为YYYY-MM-DD，publishedPrecision=date；timeEvidence包含originalText和本地observedAt，不生成虚构钟点。历史补跑不能把今天读到的“昨天”解释为历史目标日。

“N小时前/分钟前”保存原始文字，publishedPrecision=relative；published_at仅用于排序和窗口估算。以接收时间换算，并保守要求估算时刻前后各一个单位均在固定窗口内，边界不确定则隔离。网页明确显示估算。绝对日期但无时刻、无“昨天”证据的记录仍不作为窗口内文章。Manus原始输出用published_time_text，本地生成timeEvidence与精度字段；快照/feed保留这些字段。
