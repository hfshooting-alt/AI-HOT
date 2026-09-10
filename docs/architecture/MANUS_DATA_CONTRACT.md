# Manus 信源数据契约（MANUS_DATA_CONTRACT）

> 版本：2026-08-17 初版。契约变更必须先改本文件与 `tests/pipeline/test_manus_contract.py`，再改生产代码。
> 校验实现：`scripts/manus_source/contracts.py`（离线单测：`python -m unittest tests.pipeline.test_manus_contract -v`）

## 2026-09-09 十点窗口契约

- 默认统一入口使用北京时间前一日 10:00（含）至 date 当日 10:00（不含）的固定窗口。
- 窗口发现结果为 `schema_version=3`，本地附加 `collectionWindow: {start, end, timezone}`，每篇 complete 文章新增 `published_at`（含时区 ISO8601）。`published_date` 必须等于该时间在北京时间的日期，允许跨两个自然日；时间必须处于窗口内。未知时间不能用日期推算。
- 旧自然日发现结果 v2 继续可用。v2 保留“文章日期等于 target_date”的规则；不与 v3 三组混用。十点原始文件在 `work/manus/ten-am/<date>/raw/`。
- 正文批次的 target_date 代表运行批次；窗口模式逐 URL 与发现结果的实际 published_date 校验，因此前一天与当日的正文均可通过，不能替换为批次日期。
- feed 保留 schemaVersion=1，新增可选 collectionWindow；窗口 feed 的 publishedPrecision 为 datetime，publishedAt 为发现阶段核实的真实时间。历史 date 精度 feed 继续兼容，不能进入精确 24 小时日报。
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

## 3. 规范化 feed（`data/manus/current.json`，schemaVersion=1）

字段与 `tests/fixtures/manus/current.json` 一致。要点：

- `ok=true` 才可消费；`degraded=true` 表示存在来源级失败（成功文章照常发布）。
- `sourceType` 恒为 `"wechat"`（兼容现有“仅看公众号”筛选），`collector` 恒为 `"manus"`。
- `id` = `manus:` + sha256(账号|日期|归一化标题) 前 16 位（`stable_article_id`）。
- 只有日期时用北京时间 12:00 占位且 `publishedPrecision="date"`，页面不得展示为精确时间。
- `classification` 保存 taxonomy id；渲染时经 `tag_news.to_display()` 转中文。
- `contentSha256` 为正文哈希；**全文绝不进入 feed**。
- stats 自洽：`configuredAccounts = complete + failed`；`publishedArticles = len(items)`；
  `fallbackArticles` = `enrichmentStatus=fallback` 条数；`discovered >= published`。
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
