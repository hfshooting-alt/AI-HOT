# 新闻Daily 代码维护导航

## 数据流与模块边界

统一编排位于 `scripts/run_pipeline.py` 和 `scripts/automation/`。当前只采集 Manus，默认窗口为扫描开始时冻结的最近 24 小时；来源、时间、费用与发布边界见[统一新闻链路](UNIFIED_NEWS_PIPELINE.md)。

1. `scripts/manus_source/`：逐源发现、原始请求与终态诊断、checkpoint、来源/时间校验和免费正文提取。
2. `scripts/news_pipeline.py`：读取本批 Manus 结果，形成全部文章元数据和精选候选，处理去重、相关性与单条失败。
3. `scripts/enrich_news.py` / `tag_news.py`：正文摘要与分类，经 `llm_common.py` 调用配置模型。
4. `scripts/build_snapshot.py`：从处理结果生成 `all` / `garenaSelected`，不再拉 AIHOT 或用演示数据回填。
5. `scripts/build_company_overview.py` / `company_index/`：只从精选抽取公司、产品及逐字段来源，保留合法历史与审核记录。
6. `scripts/funding_table.py` / `funding/`：从精选生成融资表，独立保留融资状态与证据。
7. `web/app/_lib/data/api.ts`：只读取已发布快照、公司及融资 JSON；`news-pools.ts`：独立 Manus 双池与空/错误状态。
8. `automation/candidate.py` / `publish.py`：校验候选、锁定基线并统一晋升；静态构建与 Pages 部署随后执行。

| 修改目标 | 入口 |
| --- | --- |
| 新闻来源账号、分组与平台 | `config/manus_sources.json`、`manus_source/config.py` |
| 发现提示词与 seed 线索 | `scripts/prompts/`、`manus_source/source_seeds.py`、`source_guidance.py` |
| 任务终态、余额与停止保护 | `manus_source/client.py`、`runner.py` |
| 已知候选覆盖缺口 | `manus_source/seed_coverage.py` |
| 逐篇正文隔离与跳转识别 | `manus_source/crawler.py`、`extraction_worker.py`、`source_urls.py` |
| 来源、时间与输出契约 | `manus_source/contracts.py`、`checkpoints.py`、`window.py` |
| 全量与精选的分流 | `scripts/news_pipeline.py`、`build_snapshot.py` |
| 公司/融资输入门禁 | `company_index/inputs.py`、`funding/inputs.py` |
| 公司主体合并、归属、逐字段来源 | `company_index/entities.py`、`company_index/identity.py` |
| 公司/融资抽取和模型容量 | 各自的 `config.py`、`extraction.py` |
| 新闻首页、精选和筛选 | `web/app/_components/views/AllAIView.tsx`、`news/` |
| 公司与产品全景 | `CompanyOverviewView.tsx`、`company/CompanyOverviewTable.tsx` |
| 品牌、导航与元数据 | `layout/Sidebar.tsx`、`layout/AppShell.tsx`、`web/app/layout.tsx` |
| 数据来源迁移 | `scripts/manus_only_migration.py`，输出到新私有候选 |
| 旧公开页面退役 | `scripts/retire_legacy_public.py`，只操作指定 work/ 候选 |
| Pages 静态构建 | `scripts/build_pages.mjs`、`.github/workflows/deploy-pages.yml` |
| 本地设置 | `SettingsView.tsx`、`scripts/settings-server.mjs` |

## 保持的边界

- `newsSelectionVersion=1` 的两个显式池独立，缺池报错、空池不回填；浏览器只显示 `manus:` 文章。
- 私有正文、完整模型响应及任务 trace 留在 work/；公开文件只带摘要、必要字段证据和来源。
- 成功缓存按实际版本复用；来源迁移不能重标缓存或重置费用账本。
- 配置来源和平台身份不能互相冒充；入口可达、取得窗口样本、完整覆盖分别验收。
- `data/`、`web/public/` 是正式产物，常规代码整理不得顺手重生成；数据变更通过候选审核。
- 前端品牌为“新闻Daily”，现有 GitHub 仓库及 `/AI-HOT/` 部署路径保留。
- 旧日报、热点、上游新闻 API 和浏览器补录已删除；历史设计与验证数字以 `docs/history/` 原记录为准。

## 验证

Python 默认 `python scripts/test_pipeline.py offline`，禁止网络与付费请求。前端运行 `npm --prefix web run typecheck` 和 `npm --prefix web test`；快速检查为 `npm --prefix web run test:unit`。构建产物测试同时验证退役 API 返回 404 且没有上游请求。

候选公开清理先 plan 再 apply；保留文件有字节哈希，异常记 incomplete，不能绕过正常新闻/公司/融资与隐私校验。实际采集和 Pages 验收另行记录，离线测试通过不表示 20 个信源完整覆盖已通过。
