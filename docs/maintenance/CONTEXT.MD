# docs/maintenance/CONTEXT.MD — AI HOT 项目当前状态与实现进度

> 接手必读。最近同步：2026-09-08。配合 `docs/maintenance/AGENTS.MD`（守则）与 `docs/maintenance/MEMORY.MD`（经验教训）使用。

## 1. 项目一句话

AI 情报日报/周报看板：聚合 aihot 第三方 API 与 Manus 采集的公众号文章，经过正文提取、LLM 加工、归档和快照构建后，由 Next.js 组件化前端展示。

## 2. 当前代码基线

- 2026-09-09 成本控制：新增 `scripts/test_pipeline.py` 与 `scripts/testing/`。默认 Python 测试阻断网络和子进程；只读认证探针缓存结果；显式付费探针每日最多一次 Lite 创建尝试，限制轮询并请求停止超时/高消费任务。195 项 Python 离线测试通过。
- 2026-09-09 Manus 密钥检查：用户提供的密钥仅存本地已忽略 `.env`，两次官方余额只读请求均返回 401（含粘贴转义复核），尚未认证成功；没有创建真实任务，余额未知，DeepSeek 仍待配置。后续遵守 `docs/operations/TESTING_COST_CONTROL.md`。

- 2026-09-08 自动化加固（基于 `8b9e9f5`）：增加统一 doctor/run 入口、候选产物隔离、阶段恢复、发布回滚和过期候选保护；融资全部抽取失败禁止覆盖旧表，失败/fallback 缓存可重试。每日任务串联采集、正文、feed、快照/历史/周报和融资表。操作见 `docs/operations/AUTOMATED_PIPELINE.md`。离线验证通过；真实接口和部署仍待密钥及托管接通。本次未更新新闻数据。
- 本轮验证：185 项 Python、23 项 Node 测试及生产构建通过。实际 doctor 的配置/依赖/权限检查通过，仅缺 Manus/DeepSeek 密钥；dry-run 成功，未执行付费采集或线上发布。

- 2026-09-08 根目录收拢（基于 `8cb2bed`）：前端完整工程与 Node 测试归入 `web/`；requirements、提示词、模板归入 scripts；缓存和归档归入 data；完整交接文档归入 docs/maintenance。构建输出为 web/dist，Python 默认路径和自动任务已同步。历史迁移表保留当时位置，当前准确布局以 DIRECTORY_LAYOUT.md 为准。

- 2026-09-08 目录迁移（基于 `438aaef`）：60 个文件按功能归位；业务配置移至 `config/`，前端组件与工具分层，测试按 pipeline/frontend/api/settings 分类，文档按 guides/architecture/operations/reference/history 分类。导入、默认配置路径、测试入口与文档链接同步更新。169 项 Python 与 23 项 Node 测试、生产构建通过；业务数据、配置内容与公开数据 URL 保持不变。路径溯源见 `docs/architecture/PATH_MIGRATION.json`。

- 2026-09-08 结构整理：融资阶段实现拆到 `scripts/funding/`，原 CLI/导出保留；日报与周报详情拆到 `web/app/_components/reports/`；全部/精选 API 共用分页和归一化；前端命令兼容 Windows。功能与数据保持原基线，验证与已知静态检查问题见 `docs/architecture/CODEBASE_GUIDE.md`。

- 权威仓库：当前目录，分支 `main`。本文只描述已提交状态；接手时另行运行 `git status` 检查本地改动。
- 功能与数据基线：`645e2cf`（2026-08-28）`chore: 更新 Manus group_a 25-27 数据与快照 [skip ci]`；本次文档同步在此基础上追加，不改变功能与数据。
- 近期关键提交：`da51733`（强化 Manus discovery Prompt 自检）、`107e682`（融资动态界面与数据链路）、`7bb563c`（新分类标签体系）、`ea592dc`（快照与归档刷新）。
- 测试：2026-08-28 复核 169 个 Python 离线测试全部通过；Node 的渲染、来源类型和设置服务测试共 18 项全部通过。Pytest 仅提示 `.pytest_cache` 无写权限，不影响结果。
- 账号配置：`config/manus_sources.json` 共 20 个账号，group_a 7 个、group_b 7 个、group_c 6 个。
- Manus 默认轮询超时：`MANUS_TIMEOUT_SECONDS=3600`，用于容纳超过 10 分钟的 discovery 任务。
- 自动更新：`fetch-manus.yml` 每日北京时间 01:00 运行完整数据链路，含 `web/public/snapshot.json`、历史页及周报，全部阶段通过后提交正式产物。独立 `update-snapshot.yml` 已删除。线上托管构建/发布尚未接通。

### 当前 Manus 数据

| 日期 | 测试范围 | complete / failed 账号 | 发现 / 发布 | fallback | 状态 |
|------|----------|------------------------|-------------|----------|------|
| 2026-08-25 | 仅执行 group_a；B/C 为失败占位 | 3 / 17 | 4 / 4 | 0 | degraded |
| 2026-08-26 | 仅执行 group_a；B/C 为失败占位 | 4 / 16 | 6 / 6 | 0 | degraded |
| 2026-08-27 | 仅执行 group_a；B/C 为失败占位 | 4 / 16 | 3 / 3 | 0 | degraded，当前 feed |

- `data/manus/current.json` 当前目标日为 2026-08-27，生成时间 `2026-08-27T18:21:48+08:00`。
- `data/manus/archive/2026-08-25.json` 至 `2026-08-27.json` 已落盘；`data/archive/`、`web/public/snapshot.json`、`web/public/history/` 和 `web/public/weekly/` 已同步更新至 2026-08-27。
- 这三天的数据用于验证 Manus 更新链路。流程已贯通 discovery → content → enrich → feed → snapshot/archive；账号完成率受测试范围影响，不代表 20 个账号的正式采集质量。

## 3. 实现进度（按阶段）

### ✅ 已完成

| 阶段 | 内容 | 关键提交 |
|------|------|----------|
| S1–S3 早期看板与归档 | 单文件静态看板、CloudBase 托管、`data/archive/YYYY-MM-DD.json` 归档、自然周引擎、历史页和周报页 | 历史提交 |
| S4 WeRead 信源（已下线） | WeRead 曾短期接入，后随 Manus 路线迁移删除 | 中间态 |
| S5 AI 打标签 harness | `tag_news.py` + `eval_tagging.py`，两级分类、校验规则与评测门禁 | `d424e0b` |
| S6 Manus 唯一公众号信源 | `scripts/manus_source/`、`enrich_news.py`、`build_manus_feed.py`、`fetch-manus.yml`、数据契约与 Runbook；账号池现已扩至 20 个 | `18846ff`、`4d9c227`、`83b970e`、`6b2a6d8`、`107e682` |
| S7 Next.js 组件化前端 | Next.js 16 + React 19 + Tailwind 4；`AppShell`、五视图、API 路由和设置入口 | `d1e5e2e` |
| S8 正文脚本化 | 阶段 B 默认使用 urllib + trafilatura，本地验证过腾讯与网易正文抓取；保留 Jina 和 Manus 回退 | `85c93b3`、`e1f0287`、`d76502c` |
| S9 搜索与来源筛选 | 标题/摘要/来源/URL 搜索，来源类型启发式筛选，Manus 与 aihot 快照池合并 | `a966794`、`e251513` |
| S10 新分类与融资动态 | 六类新闻分类、标签筛选；融资动态专属表格、枚举、来源列、LLM 抽取及可选 Tavily 补全 | `7bb563c`、`107e682` |
| S11 Manus Prompt 与契约加固 | 来源三元组逐字复制、文章字段完整性、`article_count` 重算、audit 覆盖、failed 规则、根字段白名单和最终 JSON 自检 | `da51733` |
| S12 group_a 三日链路测试 | 2026-08-25 至 27 仅抓 group_a，通过 B/C 失败占位满足三组 feed 契约，完成正文、加工、晋升、归档和快照更新 | `645e2cf` |

## 4. 当前风险与待办门禁

1. **分组试跑缺少一等支持**：`runner.py --groups group_a` 可单独运行 discovery；`content_phase.py` 和 `build_manus_feed.py` 固定要求三组发现文件。当前 B/C 失败占位可验证完整链路，但会把未执行账号计为失败并生成 degraded feed。正式设计需明确 partial-run 的校验和晋升语义。
2. **Manus 结构化输出仍有波动**：任务显示成功只代表平台返回了结果。本地契约仍可能因账号字段错位、audit 计数与文章数不一致、字段缺失等问题拒绝结果。`da51733` 已强化 Prompt，自检可降低失败率，仍需通过多轮真实任务验证稳定性。
3. **三日数据属于测试样本**：25–27 日只执行 group_a，16–17 个 failed 账号大多来自未执行组占位。该数据可证明更新流程可行，无法评价 group_b/group_c 的采集覆盖率。
4. **业务内容过滤不足**：2026-08-26 数据中包含标题为“日常模板（不带推荐阅读）”的占位内容。契约保证字段和链路完整，暂未设置新闻有效性过滤门槛。
5. **自动数据更新已接通，真实运行待验证**：统一编排和失败保护通过离线测试；当前本地 doctor 仅报告缺少 MANUS_API_KEY 和 DEEPSEEK_API_KEY，未调用付费接口。GitHub Secrets 和全量 CI 实跑另行验证。
6. **CI 与全账号覆盖待验证**：需确认 GitHub Secrets、数据中心 IP 抓取表现，以及 20 个账号完整运行的耗时和成功率。必要时启用 `MANUS_CRAWL_JINA_FALLBACK=true` 或 `MANUS_CONTENT_MODE=manus`。
7. **Windows 前端命令兼容已修复**：dev/build/start 统一通过 `scripts/vinext.mjs` 设置环境并在 `web/` 执行；生产构建已验证。
8. **Next.js 发布切换未完成**：CloudBase 线上仍以静态产物为主，`vinext build` 产物的正式上传路径尚未落地。

## 5. 2026-08-27 至 28 验证结论

- group_a 的 25–27 日发现、正文抓取、LLM 加工、feed 构建、原子晋升、历史归档和快照生成均已完成，流程可用。
- Prompt 加固前的真实失败包含：白鲸出海返回 `account_name=null` 且把账号名写进 `source_platform`；极客公园 audit 声称 4 篇但最终只返回 3 篇；另有 URL 日期与 `published_date` 不一致的数据质量风险。
- 上述案例说明本地契约校验有必要。Prompt 已增加来源常量、字段完整性、计数重算和最终 JSON 自检；稳定性结论需等待重复运行和全组测试。
- 25–27 日发布条目 fallback 均为 0；2026-08-20 曾出现的 6/15 fallback 属历史样本，当前不再作为这轮测试的主要阻塞项。

## 6. 下一步建议（按优先级）

1. 对 group_a 连续重复运行相同日期或新日期，统计 Prompt 加固后的契约通过率和字段错误类型。
2. 完成一次 group_a/group_b/group_c 全量 discovery，验证 20 个账号、1 小时客户端超时和 CI 240 分钟作业上限。
3. 设计正式 partial-run 模式，使未执行组与真实失败来源分开统计，并默认禁止部分结果覆盖生产 feed。
4. 增加模板页、空内容和非新闻页面的业务质量门槛。
5. 配置密钥后先执行统一入口 `--no-promote` 实跑，检查候选数据，再 `--resume` 发布；验证 CI 全流程。
6. 确认 Next.js 的线上发布方案并接通托管。

## 7. 变更日志

- 2026-08-19：首次建立三份交接文档（AGENTS/MEMORY/CONTEXT），截图归档至工作区 `screenshots\`。
- 2026-08-21：同步正文脚本爬虫、schema_version 修复、Next.js 搜索与来源筛选。
- 2026-08-28：同步 20 账号配置、融资动态、分类体系、Manus 1 小时超时、discovery Prompt 加固，以及 group_a 25–27 日完整链路测试和数据晋升结果。
