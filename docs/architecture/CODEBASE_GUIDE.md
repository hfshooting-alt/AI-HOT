# 代码维护导航

## 数据流与模块边界

统一编排在 `scripts/run_pipeline.py` 和 `scripts/automation/`：检查、阶段命令、候选产物、恢复和发布保护。日常操作见[自动流水线](../operations/AUTOMATED_PIPELINE.md)，下列模块继续负责各自业务逻辑。

1. `scripts/manus_source/` 负责发现任务、正文抓取与契约校验；配置来自 `config/manus_sources.json`。
2. `scripts/enrich_news.py` 加工正文，`scripts/tag_news.py` 按 `config/taxonomy.json` 分类；两者复用 `llm_common.py` 调用模型。
3. `scripts/build_manus_feed.py` 组装、校验并晋升 `data/manus/current.json`。
4. `scripts/build_snapshot.py` 合并 AIHOT API 和 Manus feed，生成快照、日报与周报归档。它负责时间窗口、定稿与保留策略。
5. `scripts/funding_table.py` 保留命令行与原有 Python 导入接口，协调 `scripts/funding/` 各阶段生成融资公司表。
6. `scripts/build_company_overview.py` 协调 `scripts/company_index/`，从全部新闻类别持续更新公司/产品实体和逐字段来源。
7. `web/app/_lib/data/api.ts` 读取快照和本站 API；`web/app/api/` 代理上游；`web/app/_components/` 渲染页面。

融资模块依赖方向：`inputs`、`extraction`、`companies`、`search`、`output` → `config` 或公共 LLM/缓存工具；总流程位于兼容入口 `funding_table.py`。阶段模块不反向导入入口。

公司库模块依赖方向：`inputs`、`extraction`、`entities`、`output` → `config` 或现有公司名归一化工具；成功抽取缓存和历史 `current.json` 共同保证增量更新。模型调用上限与时间预算由 taxonomy 配置，前端读取 `web/public/company-overview.json`。

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
| 全类别公司/产品输入与正文匹配 | `scripts/company_index/inputs.py` |
| 公司/产品抽取与调用预算 | `scripts/company_index/extraction.py` |
| 实体去重、历史合并与字段溯源 | `scripts/company_index/entities.py` |
| 公司库输出契约与晋升 | `scripts/company_index/output.py` |
| 快照、归档、定稿、日期窗口 | `scripts/build_snapshot.py` |
| 全部动态 API 的分页 | `web/app/_lib/data/items-pool.ts` |
| 上游 ID、来源、分类转换与排序 | `web/app/_lib/data/news-normalization.ts` |
| 首页搜索筛选、列表与融资表切换 | `web/app/_components/views/AllAIView.tsx`、`web/app/_components/news/CategoryTabs.tsx` |
| 公司全景独立页面 | `web/app/_components/views/CompanyOverviewView.tsx` |
| 公司与产品 Overview 表格、排序分页与详情来源 | `web/app/_components/company/CompanyOverviewTable.tsx`、`CompanyDetailDrawer.tsx` |
| GitHub Pages 静态构建与部署 | `scripts/build_pages.mjs`、`.github/workflows/deploy-pages.yml` |
| 日报/周报导航 | `web/app/_components/views/DailyReportView.tsx` |
| 日报/周报详情与加载、失败展示 | `web/app/_components/reports/` |
| 配色、布局、公共新闻卡片 | `web/app/globals.css`、`web/app/_components/news/ArticleCard.tsx` |
| 本地模型设置 | `SettingsView.tsx`、`scripts/settings-server.mjs` |

## 保持兼容的约定

- 现有脚本路径和参数供工作流调用，拆模块后继续保留入口与导出。
- 上游列表最多读取三页、每页 50 条；空页也代表连接成功；后续页失败保留前面的数据。
- ID、来源链接、分类枚举、排序、提示词版本、缓存键和输出字段均属于行为契约。
- `web/public/`、`data/`、`data/archive/` 中有受版本管理的数据产物。结构整理不重新生成这些文件；`web/build/` 保存 Sites Vite 插件源码。
- `config/accounts.json` 是候选来源池；线上 Manus 来源使用 `config/manus_sources.json`。
- `web/db/`、`web/drizzle/`、`web/examples/`、`web/worker/` 保留部署脚手架；当前 `web/.openai/hosting.json` 未启用 D1/R2。
- 历史方案已集中到 `docs/history/`；当前操作以 README、运行手册和现有代码为准。完整布局与旧路径映射见 [目录分工](./DIRECTORY_LAYOUT.md)。

## 验证

2026-09-09 信息架构调整：删除独立精选视图、接口与快照字段；全部 AI 动态成为默认首页，公司与产品全景成为第二个独立页面并在无模型数据时展示完整空表结构。ICP 文案已移除。

2026-09-09 静态站点与公司库增强：公司表新增排序、24 条分页、完整档案抽屉和逐字段/逐文章来源；GitHub Pages 已发布到 `https://hfshooting-alt.github.io/AI-HOT/`，全部动态、公司全景、热点榜和日报在 `/AI-HOT/` 子路径可访问。全仓库 TypeScript 检查已修复并通过；Pages 构建本身不调用付费 API。

2026-09-09 前端视觉升级：生产构建和本次变更文件 ESLint 通过；使用离线公司样例检查 1440px 桌面布局与 390px 手机布局，样例检查后删除，未进入正式数据。

2026-09-09 十点窗口验证：202 项 Python 离线测试、23 项 Node 测试及生产构建通过，新增覆盖跨年窗口、十点边界、UTC 换算、延迟启动、未知时间拒绝、三组跨日正文恢复、真实时间透传、上游入库/日报窗口一致性及旧模式运行隔离。网页托管部署未开启。

2026-09-09 新增成本保护后，195 项 Python 测试通过 `python scripts/test_pipeline.py offline` 验证。此入口默认阻断真实网络和子进程，是后续 Python 回归的首选。认证与付费探针分开，细节见[测试成本控制](../operations/TESTING_COST_CONTROL.md)。

2026-09-08 自动化加固验证：185 项 Python 离线测试、23 项 Node 测试和生产构建通过。新增覆盖失败缓存重试、全部抽取失败保护、阶段恢复、目录替换异常回滚、中断日志恢复、配置变化及旧候选覆盖拒绝，以及全流程固定样本联调。doctor 实际检查仅缺 Manus/DeepSeek 密钥；dry-run 正常。未调用付费接口，未重生成正式新闻数据。

修改 Python 流水线后运行 `python -m unittest discover -s tests -p "test_*.py"`；修改前端/API 后运行 `npm --prefix web test`。`npm --prefix web run test:unit` 可快速检查来源、分页与设置服务。

2026-09-08 整理验证：169 项 Python 测试、23 项 Node 测试和生产构建通过。新增回归覆盖分页边界及构建后的全部动态接口、来源、排序、缓存和失败响应。融资 35 个函数的 AST 与整理前相同；日报与周报详情函数体保持一致。现有测试使用模拟接口；不代表真实付费服务端到端验证。

基线 `9cec544` 曾存在的 TypeScript 问题已修复：周报分类补齐 `catLabel`，Cloudflare/Vite 环境声明补齐，D1 示例导入路径已更正。日报与周报详情的 effect 同步更新 loading 仍属于既有 React lint 告警；本次没有关闭规则。

依赖版本与两份锁文件保持不变。Python `scripts/requirements.txt` 延续现有工作流的依赖范围；尚未建立完整的 Python 版本锁定。

根目录工程拆分后，Node 依赖及测试由 `web/package.json` 管理，命令从仓库根使用 `npm --prefix web ...`。最新路径以 [根目录地图](DIRECTORY_LAYOUT.md) 和 [第二次迁移表](ROOT_PATH_MIGRATION.json) 为准。
