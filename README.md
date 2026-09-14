# AI HOT

全量测试既有扫描内容：`python scripts/review_all_scanned.py --snapshot <快照> --feed <feed> --previous <已有公司库> --output work/<候选目录> --allow-paid`。逐篇 DeepSeek 重打标并抽取被提及公司，成功结果缓存；公司更新日期表示最新报道时间，旧资料回填不覆盖较新字段。不会触发 Manus 或发布正式数据。

最近进展：[公司国家补全与 Manus 来源排障](docs/history/2026-09-10/COUNTRY_AND_MANUS_REVIEW.md)。

中文 AI 情报看板，聚合 AIHOT API 与 Manus 核验的媒体内容，以全部动态为首页，并提供公司与产品全景、热点、AIHOT 八点日报、本站周报、融资公司表和本地模型设置。

前端使用 React、Next.js API 与 vinext/Vite；数据流水线使用 Python。现有数据以 JSON 快照与归档保存。

已筛选新闻可用 `scripts/review_cached_news.py` 在 `work/` 中复核摘要和公司库：默认4篇、累计最多8次模型请求，显式 `--allow-paid` 才调用；不抓取信源、不更新正式数据。来源异常定位见 [9月10日复核记录](docs/history/2026-09-10/SOURCE_DIAGNOSIS_20260910.md)。

## 本地启动

公司库按“筛选表格 → 公司详情卡片”展示，零结果保留筛选栏和表头。`config/company_research.json` 保存经审阅的官网归属与补全证据，品牌资料保留在母公司档案下，原始文章仍可追溯。

需要 Node.js >=22.13.0 和 Python >=3.10。Windows、macOS、Linux 使用相同的前端命令：

```sh
npm --prefix web ci
python -m pip install -r scripts/requirements.txt
npm --prefix web run dev
```

也可使用仓库现有的 pnpm 锁文件：`pnpm --dir web install --frozen-lockfile`。依赖安装遵循本地包管理器的构建审批策略；不要混用包管理器更新锁文件。

按 `config/env.example` 在根目录配置 `.env`，或运行 `node scripts/settings-server.mjs` 后使用设置页。仅查看已有快照无需调用付费采集/模型接口；运行采集需要配置相应密钥。

## 常用命令

自动更新统一入口：`python scripts/run_pipeline.py doctor` 检查环境；`python scripts/run_pipeline.py run --dry-run` 查看执行计划。默认 `full` 模式并行采集 AIHOT 与 Manus，合并去重后统一进行模型筛选、摘要分类、公司库和融资更新。`--source-mode aihot-only` 只关闭 Manus，仍需模型密钥并执行后续加工；它保留 AIHOT 提供的各类来源。部分采集失败允许发布成功来源，页面明确列出缺失来源；模型加工失败则保留上一版。统一入口支持 `--resume`、`--stage` 和 `--no-promote`，详见[自动流水线操作说明](docs/operations/AUTOMATED_PIPELINE.md)和[统一新闻链路](docs/architecture/UNIFIED_NEWS_PIPELINE.md)。

每日任务按北京时间 **09:30 开始**，固定采集前一天 09:30（含）至当天 09:30（不含）的新闻；全部加工成功后更新仓库中的网页产物，并触发 GitHub Pages 重新部署。GitHub 定时调度可能延迟。`--date` 在默认固定窗口模式下表示窗口结束日，旧自然日流程使用 `--window-mode calendar-day`。

公司收录、新闻筛选、资料证据及双日期定义以[投资人验收口径](docs/operations/INVESTOR_ACCEPTANCE.md)为准。新业务口径先在隔离候选批次中验收，再发布。

Manus 支持保留同一来源已核实的部分文章；未扫完整个窗口时标明“部分覆盖”，继续执行时间、正文及模型审核，不因止损删除已验证成果。该机制不保证每次任务都能在预算内取得文章。

当前公开站点使用无后端静态模式，地址为 [https://hfshooting-alt.github.io/AI-HOT/](https://hfshooting-alt.github.io/AI-HOT/)。它读取仓库已有快照，不需要 Manus 或模型 API；在新的采集数据尚未生成时会继续展示现有快照。Manus 条目先经过 AI 相关性门禁，再进行摘要、标签和公司抽取；实际承载页会标记为官网资讯、腾讯新闻转载、网易号转载或已核实公众号。仓库 Pages Source 已设为 **GitHub Actions**。

| 命令 | 用途 |
| --- | --- |
| `npm --prefix web run dev` | 本地开发 |
| `npm --prefix web run build` / `npm --prefix web start` | 生产构建 / 启动 |
| `npm --prefix web run build:pages` | 生成 `web/dist/client` 静态站点；不访问付费 API |
| `npm --prefix web test` | 构建及全部 Node 测试 |
| `npm --prefix web run test:unit` | 来源、分页和设置服务测试 |
| `python scripts/test_pipeline.py` | Python 离线回归，禁止真实网络/子进程 |
| `python scripts/test_pipeline.py manus-auth` | 只读检查 Manus 认证与余额，结果有缓存 |
| `python scripts/test_pipeline.py llm-smoke --allow-paid` | 单次最多 16 token 的模型 JSON 能力检查，每日最多一次 |
| `python scripts/run_pipeline.py run --source-mode aihot-only --no-promote` | 不调用 Manus，使用模型生成新闻与公司库候选产物 |
| `python scripts/audit_manus_sources.py [--check-links]` | 离线审计公众号配置；可选每个主页一次无重试可达性检查 |
| `python scripts/manus_source/runner.py --date YYYY-MM-DD --ten-am --account "账号名" --allow-paid` | 单账号 Lite 来源校准，结果与生产隔离 |
| `npm --prefix web run typecheck` / `npm --prefix web run lint` | 静态检查；已有问题见维护导航 |
| `python scripts/build_company_overview.py --no-promote` | 生成并校验公司与产品库；会调用模型 |
| `python scripts/funding_table.py --selftest` | 融资流程离线自检 |

采集和快照命令会访问外部服务或更新数据，具体参数见运行手册。

## 目录

```text
AI-HOT/
├── web/           完整前端工程、配置、锁文件、公开资源和 Node 测试
├── scripts/       数据流水线、提示词、模板、Python 依赖与本地服务
├── config/        信源、分类和环境变量示例
├── data/          Manus/公司与产品/融资数据、每日归档与分类缓存
├── tests/         Python 流水线测试、固定样本与人工评测集
├── docs/          使用指南、架构、运维、开发交接与历史记录
├── .github/       自动任务
├── README.md      项目首页
├── AGENTS.MD      简短开发入口
├── .gitignore     全仓库忽略规则
└── .editorconfig  全仓库编辑规范
```

前端的 `package.json`、两份锁文件及 Vite、Next、TypeScript、ESLint、PostCSS、Drizzle 配置均位于 `web/`。Python 依赖位于 `scripts/requirements.txt`；分类缓存位于 `data/cache/tag_cache.json`；完整交接文档位于 `docs/maintenance/`。

从[完整目录地图](docs/architecture/DIRECTORY_LAYOUT.md)查看详细分工；[文档入口](docs/README.md)提供阅读顺序。

## 维护文档

- [代码维护导航](./docs/architecture/CODEBASE_GUIDE.md)：数据流、修改位置、兼容约定、验证结果。
- [Manus 运行手册](./docs/operations/MANUS_SOURCE_RUNBOOK.md)、[数据契约](./docs/architecture/MANUS_DATA_CONTRACT.md)。
- [部署说明](./docs/operations/DEPLOY_WORKFLOW.md)、[使用说明](./docs/guides/USER_GUIDE.md)。
- [开发守则](./docs/maintenance/AGENTS.MD)、[当前状态](./docs/maintenance/CONTEXT.MD)、[长期经验](./docs/maintenance/MEMORY.MD)。
- [Sites 脚手架参考](./docs/reference/SITES_TEMPLATE.md)：保留原始模板的可选数据库、身份与托管说明。

## 每日数据与网页发布

机器之心采集入口已改为官网产业资讯页，只收录机器之心署名文章，按官网渠道展示；配置切换不代表完整采集已验收。ZPotential 的备用入口及覆盖限制见 `docs/history/2026-09-10/SOURCE_DIAGNOSIS_20260910.md`。

每日采集完成并提交正式数据后，工作流显式触发 GitHub Pages 部署；没有数据变化时跳过。候选测试不更新正式网页，部署是否完成以 Pages 工作流结果为准。


## 2026-09-14：单条隔离与“昨天”收录口径

用户确认单条失败不得阻断整批。相关新闻缺证据、摘要分类未通过时，写入collectionStatus.quarantined及计数，不进入新闻或公司证据输入；公司抽取失败写入articleFailures，已有资料保留。来源、模型阶段整体不可用和跨产物校验失败仍保护旧网页。前端显示隔离数量、原因与原文链接。

绝对时间维持北京时间前一日09:30至当天09:30的固定窗口。原文或对应卡片标注“昨天”时，按采集记录接收时间（北京时间）的前一自然日全天纳入，这是用户授权的日期精度例外，不宣称严格24小时覆盖。published_at为YYYY-MM-DD，publishedPrecision=date；timeEvidence包含originalText和本地observedAt，不生成虚构钟点。历史补跑不能把今天读到的“昨天”解释为历史目标日。

“N小时前/分钟前”保存原始文字，publishedPrecision=relative；published_at仅用于排序和窗口估算。以接收时间换算，并保守要求估算时刻前后各一个单位均在固定窗口内，边界不确定则隔离。网页明确显示估算。绝对日期但无时刻、无“昨天”证据的记录仍不作为窗口内文章。Manus原始输出用published_time_text，本地生成timeEvidence与精度字段；快照/feed保留这些字段。

本轮后续修正见 docs/operations/QUALITY_CORRECTIONS_20260914.md：新闻分类与产品归属独立，个人产品保留pendingEntities并展示；已核实旧闻逐条隔离，未泛化为全网原文时间已验证。
