# 代码维护导航

## 数据流与模块边界

1. `scripts/manus_source/` 负责发现任务、正文抓取与契约校验；配置来自 `config/manus_sources.json`。
2. `scripts/enrich_news.py` 加工正文，`scripts/tag_news.py` 按 `config/taxonomy.json` 分类；两者复用 `llm_common.py` 调用模型。
3. `scripts/build_manus_feed.py` 组装、校验并晋升 `data/manus/current.json`。
4. `scripts/build_snapshot.py` 合并 AIHOT API 和 Manus feed，生成快照、日报与周报归档。它负责时间窗口、定稿与保留策略。
5. `scripts/funding_table.py` 保留命令行与原有 Python 导入接口，协调 `scripts/funding/` 各阶段生成融资公司表。
6. `web/app/_lib/data/api.ts` 读取快照和本站 API；`web/app/api/` 代理上游；`web/app/_components/` 渲染页面。

融资模块依赖方向：`inputs`、`extraction`、`companies`、`search`、`output` → `config` 或公共 LLM/缓存工具；总流程位于兼容入口 `funding_table.py`。阶段模块不反向导入入口。

| 要修改的内容 | 优先查看 |
| --- | --- |
| 信源账号、分组 | `config/manus_sources.json`、`scripts/manus_source/config.py` |
| 发现提示词、正文提取 | `scripts/prompts/`、`scripts/manus_source/crawler.py` |
| 摘要、标签、模型参数 | `enrich_news.py`、`tag_news.py`、`config/taxonomy.json` |
| 融资输入、正文匹配 | `scripts/funding/inputs.py` |
| 融资抽取提示词、重试、抽取缓存 | `scripts/funding/extraction.py` |
| 公司归一化、去重、新旧字段合并 | `scripts/funding/companies.py` |
| 搜索补全、TTL、来源留痕 | `scripts/funding/search.py` |
| 融资输出校验、原子写入 | `scripts/funding/output.py` |
| 快照、归档、定稿、日期窗口 | `scripts/build_snapshot.py` |
| 全部/精选 API 的分页 | `web/app/_lib/data/items-pool.ts` |
| 上游 ID、来源、分类转换与排序 | `web/app/_lib/data/news-normalization.ts` |
| 页面搜索筛选、列表与融资表切换 | `web/app/_components/views/FeaturedView.tsx`、`AllAIView.tsx` |
| 日报/周报导航 | `web/app/_components/views/DailyReportView.tsx` |
| 日报/周报详情与加载、失败展示 | `web/app/_components/reports/` |
| 配色、布局、公共新闻卡片 | `web/app/globals.css`、`web/app/_components/news/ArticleCard.tsx` |
| 本地模型设置 | `SettingsView.tsx`、`scripts/settings-server.mjs` |

## 保持兼容的约定

- 现有脚本路径和参数供工作流调用，拆模块后继续保留入口与导出。
- 上游列表最多读取三页、每页 50 条；空页也代表连接成功；后续页失败保留前面的数据。精选首请求失败仍使用原有无缓存响应。
- ID、来源链接、分类枚举、排序、提示词版本、缓存键和输出字段均属于行为契约。
- `web/public/`、`data/`、`data/archive/` 中有受版本管理的数据产物。结构整理不重新生成这些文件；`web/build/` 保存 Sites Vite 插件源码。
- `config/accounts.json` 是候选来源池；线上 Manus 来源使用 `config/manus_sources.json`。
- `web/db/`、`web/drizzle/`、`web/examples/`、`web/worker/` 保留部署脚手架；当前 `web/.openai/hosting.json` 未启用 D1/R2。
- 历史方案已集中到 `docs/history/`；当前操作以 README、运行手册和现有代码为准。完整布局与旧路径映射见 [目录分工](./DIRECTORY_LAYOUT.md)。

## 验证

修改 Python 流水线后运行 `python -m unittest discover -s tests -p "test_*.py"`；修改前端/API 后运行 `npm --prefix web test`。`npm --prefix web run test:unit` 可快速检查来源、分页与设置服务。

2026-09-08 整理验证：169 项 Python 测试、23 项 Node 测试和生产构建通过。新增回归覆盖分页边界及构建后的全部/精选接口过滤、来源、排序、缓存和失败响应。融资 35 个函数的 AST 与整理前相同；日报与周报详情函数体保持一致。现有测试使用模拟接口；不代表真实付费服务端到端验证。

基线 `9cec544` 与整理后均存在以下静态检查问题：`api.ts` 周报分类的 `catLabel` 可选性不一致；Cloudflare 的 `cloudflare:workers`、`Fetcher`、`D1Database` 声明缺失；日报与周报详情的 effect 同步更新 loading 触发 React lint。`npm --prefix web run typecheck` 和相关 lint 尚未全绿。这些问题已在独立原始代码目录复现，本次保留运行逻辑，也未关闭检查规则。

依赖版本与两份锁文件保持不变。Python `scripts/requirements.txt` 延续现有工作流的依赖范围；尚未建立完整的 Python 版本锁定。

根目录工程拆分后，Node 依赖及测试由 `web/package.json` 管理，命令从仓库根使用 `npm --prefix web ...`。最新路径以 [根目录地图](DIRECTORY_LAYOUT.md) 和 [第二次迁移表](ROOT_PATH_MIGRATION.json) 为准。
