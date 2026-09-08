# Manus 信源数据契约（MANUS_DATA_CONTRACT）

> 版本：2026-08-17 初版。契约变更必须先改本文件与 `tests/pipeline/test_manus_contract.py`，再改生产代码。
> 校验实现：`scripts/manus_source/contracts.py`（离线单测：`python -m unittest tests.test_manus_contract -v`）

## 总览

| 契约 | 载体 | 生产者 | 校验函数 |
|---|---|---|---|
| 发现结果（schema v2） | `work/manus/<date>/raw/discovery-<group>.json` | Manus 发现任务 | `validate_discovery()` |
| 正文批次 | `work/manus/<date>/raw/content-batch-NN.json` | 本地脚本爬虫（`crawler.py`，trafilatura；可选 Manus 正文任务回退） | `validate_content_batch()` |
| 规范化 feed | `data/manus/current.json` + `archive/YYYY-MM-DD.json` | `build_manus_feed.py` | `validate_feed()` |
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
