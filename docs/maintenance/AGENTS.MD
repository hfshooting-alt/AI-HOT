# docs/maintenance/AGENTS.MD — 新闻Daily 项目 Agent 开发守则

2026-09-23最新授权（优先于下方旧默认及预算）：用户确认暂时完全不用Manus，默认与full别名均为direct-only，GitHub定时与手动仅all/direct-only，恢复默认UTC cron `30 1 * * *`（北京时间每日09:30），不恢复Codex定时跟进。定时以本次run created_at转北京时间最近已到达的09:30冻结前24小时，09:30前创建取前一天；身份/时间审计失败在付费前停止。排队跨午夜与重跑不滑窗，手动仍冻结rolling-24h。前端设置页删除，配置使用.env/Secrets；独立后台设置服务和CLI兼容保留，无设置UI。新闻列表/正文由匿名HTTP读取，所有模型处理统一现有并行科技DeepSeek-V4-Pro。config/services.json暂停Manus/Tavily真实HTTP，保留旧实现、密钥和历史证据，不自动恢复。用户允许充分使用此API，直采默认--research-full-review按有限的待补全主体队列执行，取消5主体/10页/5次日上限，每输入最多2页/1次新模型；缓存、账本、失败不重试、认证/支付/系统异常熔断及逐字段网页证据保持。默认小样本和历史恢复保留旧预算语义。此授权不要求重复已完成新闻批次，更不意味着模型凭记忆能当联网结果。

2026-09-23 新增授权：匿名媒体页面直采 `direct-only`，沿既定20来源、北京时间冻结窗口、独立分类与精选后实体抽取规则。`collector=direct_site`、`direct:` ID，feed schema3保留兼容路径。AIHOT继续关闭，此模式不创建Manus任务；调度按上方最新授权。运行限制与证据见[媒体页面直采](../operations/DIRECT_NEWS_COLLECTION.md)。此更新优先于下方“仅Manus”历史描述。

2026-09-23独立打标规则与当时批次记录（下述待处理数量、Opus状态为历史，当前结果见CONTEXT）：所有合格正文独立生成摘要与分类，相关性筛选和摘要分类逻辑解耦，不承诺网络请求并行。非精选也须打标，非AI内容不强制填写AI维度；缺正文显示“待正文”，不得凭标题分类。有正文未处理/失败分别记录pending/failed，不与garenaSelection混用。公司/产品/融资仍仅消费精选。当前27篇正文预计复用11篇旧成功、补处理16篇缺项；Jev若成功可按原规则新增精选及单篇公司处理，不冻结成员数。Opus253修正尚未晋升，所有新结果统一候选审核发布，不提前更新旧发布统计。规则、技术原因及私有逐篇诊断入口见[独立打标调整](../architecture/UNIFIED_NEWS_PIPELINE.md#2026-09-23-独立打标调整)。

2026-09-22 历史授权（Manus及定时状态已由上方最新规则替代，不作为当前执行指令）：项目品牌改为“新闻Daily”，生产仅保留 Manus 链路，停止 AIHOT 请求并清除其公开新闻及仅由 AIHOT 支撑的公司/产品/融资。共享主体保留 Manus 关联和独立资料证据。首页为全部文章，Garena投资精选独立筛选，公司/产品/融资只从精选抽取；空池不得回退旧数据。Manus 仅发现标题、链接、来源、原始发布时间，正文交由脚本；不再要求机器之心回传正文。北京时间滚动24小时截止时刻由 NEWS_COLLECTION_END 固定，严格保留原始发布时间及已确认“昨天全天”例外。20来源最多并发3个，本次追加全量扫描明确取消费用观察止损（--manus-credit-limit 0），不代表免除余额不足/创建状态不明保护，也不自动改变以后运行的默认额度。定时保持关闭；仓库与 /AI-HOT/ 部署路径兼容保留。删除与发布须在隔离候选中核验后通过 reviewed-candidate 晋升，不改写历史原始轨迹。

2026-09-22 历史Manus来源修复（当前服务暂停）：完整窗口采用逐来源内联指令与平台短路线，公开列表seed仅作线索、不可直接入库。实际请求与终态verbose轨迹只存私有work，加密恢复；诊断不影响付费任务生命周期。确认stopped后最多15秒迟到回收，仍完整校验。20源验收须分入口、窗口样本、完整覆盖；费用不自动扩大，定时保持关闭。见[来源验收](../operations/MANUS_SOURCE_VERIFICATION.md)。

2026-09-22 新闻阅读分为“全部文章”与“Garena投资精选”。全部文章保留通过既有来源/时间校验的所有去重 Manus 元数据；相关性排除和单条加工失败不删除合规元数据。摘要分类按上方9月23日规则独立处理。公司/产品/融资新增严格只读 `snapshot.garenaSelected`，空池不能回退全量、旧 feed 或历史。旧库仅保留 Manus 关联和独立公开资料，继续原预算联网补全。`newsSelectionVersion=1` 配合 `all` / `garenaSelected` 两池；独立 garenaSelection 不使用旧上游 selected。详细契约见统一新闻链路文档。

2026-09-18用户更正：机器之心网站文章作者缺失可为null，不得作为拒收理由。校验配置入口、同站文章URL与发布时间；明确识别的ScienceAI/新闻资讯等第三方发布者仍沿用原有区分。正文提取对该站增加匿名浏览器回退，不能关闭安全检查、绕过真实登录墙或验证码。

2026-09-15：用户授权完成当前全库联网资料复核，本轮73次DeepSeek请求共享台账，失败不自动重试、无Manus调用。该一次性授权不改变每日采集费用边界。`research.propose(full_review=True)`仅供显式全库复核，默认仍最多5次。注册日期证据用dateBasis=registration及legalEntity区分控股法人；countryBasis注明总部/登记/公司地址来源。已审阅fact.replace=true可更新旧值并保留旧证据，未经审阅不直接替换。内部部门source_kind=division合并新闻但不变成产品。

公司联网补全入口及证据边界见[操作说明](../operations/COMPANY_WEB_RESEARCH.md)。GLM-4V搜索结果只是线索；不能用模型回答或未经核对的搜索摘要自动写入公司库。旧模型原生搜索试验与Manus链接发现保持停用；当前只做已知网页直读与DeepSeek-V4-Pro补全，以操作说明为准。

2026-09-14用户更新：允许提高搜索测试预算，优先更强模型，失败路线不继续重复。最近扩大预算试验上限8次，实际1次Baichuan-M3即因来源质量停止。该授权不改变Manus限制，不意味着需要用满额度，也不意味着名称更新的模型自动具有搜索能力。现有GLM-4V和Baichuan-M3暂停生产接入；新证据/通道出现前不再重复失败测试。

所有来源只依据文章原始发布／发送时间收录，新增点赞、评论、互动、编辑或转载页面的刷新时间均不能使旧文章重新符合窗口。“昨天”等相对文字必须指文章发布，不得引用评论或互动时间。URL路径日期不作为发布时间判定。GitHub 定时为 UTC `30 1 * * *`（北京时间每天09:30）。校验本次run审计状态、event、ID、attempt及head SHA后，以created_at转北京时间最近已到达的09:30为截止点（09:30前创建取前一天），冻结此前24小时；创建时间无法可靠取得时在付费前停止。排队跨午夜及重跑不滑窗。手动默认启动时冻结rolling-24h，显式window-end与恢复沿原窗口。`NEWS_COLLECTION_END`贯穿所有阶段。“昨天”发布的自然日例外保持，不能伪造时分或宣称严格24小时覆盖。

> 本文件面向所有参与本项目的 coding agent，交接必读。最近同步：2026-09-23。日期明确的旧一次性预算授权不代表当前可重复使用。

用户已确认公司产品库允许基金会／开源组织主体，保留foundation/open_source_organization类型及官网证据；不归给赞助商。非商业主体产品关系在前端显示“维护”。reviewed research通过owner_entity_type与entity_type_evidence恢复审核类型，不能让后续模型抽取将其永久改为公司。

## 当前资料补全与历史预算边界

当前direct-only启用research-full-review，按顶部授权取消旧日请求数上限，但云端同日同owner租约、请求前占位、恢复与失败保护保持；本地共享账本无云租约要求。以下有日期的旧额度和Manus规则仅供历史回放，不授权恢复暂停服务。

2026-09-20：已知网页补全按北京时间执行日5主体/10页/5模型请求，在独立私有账本请求前预留；同日旧发布状态导入、未发布失败和跨run均不能重置用量。GitHub另需整批租约保存并读回确认，缓存缺失时查保留的运行历史，无法证明可用则跳过可选补全。成功建议可无新增请求恢复并保留原核验日期；这些保证不覆盖其他环境或整个API账户。基本资料和待归属主体优先；网页与模型结果分开追溯。系统性模型异常停止可选补全、保留已完成字段。不得把服务器所在地当公司国家，也不得经网页补全绕过单轮融资/市值字段门禁。具体实现与限制见公司资料操作说明。

Manus 新闻任务创建至少间隔 7 秒，共享线程锁；失败请求也占间隔，429 后后续创建冷却 60 秒。余额不代表请求频率无限制；官方 task.create 为每用户每分钟 10 次，其他进程及密钥也共享限额。所有输出对象 properties 必须全部进入 required 且 additionalProperties=false；nullable 字段也不例外。修改 schema 后运行离线契约检查，禁止以付费重试代替格式检查。

离线测试必须自行提供模型配置，不能依赖开发机 LLM_MODEL 或根目录 .env。统一入口会隔离它们，临时 dotenv 文件测试仍可使用。流水线相关提交由 .github/workflows/test-pipeline.yml 执行无密钥回归；不要给离线检查注入生产 Secrets 来掩盖夹具缺项。

历史overview小样本的已知网页补全原授权：最多 5 个主体、10 页、5 次 DeepSeek 请求。可选公司资料 Manus Lite 链接发现每天最多 1 个公司或待归属产品、20 credits 观察止损、创建不重试，与新闻媒体配额分开；本轮迁移扫描没有扩大或重置该预算。当时统一入口为 `manus-only` / `full`；当前已改为direct-only/full，Manus和AIHOT均拒绝。自动字段仅补空白并标暂定，候选归属不合并公司。配额缓存、失败处理及证据口径见[操作说明](../operations/COMPANY_WEB_RESEARCH.md)。历史数字及旧启用状态见[整理前快照](../history/2026-09-15/maintenance-before-organization/AGENTS.MD)。

## 1. 目录地图（先看这里，避免迷路）

| 路径 | 说明 |
|------|------|
| 仓库根目录 | 权威项目目录，所有运行命令从这里执行 |
| `web/app/` | 网站路由与按功能分类的组件、数据工具 |
| `config/` | 当前信源、分类与候选账号配置 |
| `scripts/` | 稳定 CLI 入口、Manus 与融资阶段实现 |
| `tests/` | pipeline、frontend、api、settings 与 fixtures |
| `docs/README.md` | 文档阅读入口 |
| `docs/architecture/DIRECTORY_LAYOUT.md` | 目录分工与路径兼容边界 |
| `docs/architecture/PATH_MIGRATION.json` | 2026-09-08 迁移前后的精确文件路径 |

截图仍按 §7 集中存放。迁移了三份业务配置，显式路径参数使用 `config/` 前缀；脚本命令入口、公开 URL、数据与缓存位置保持稳定。

- Shell 内联命令中的中文路径会被控制台编码破坏：执行脚本时先 `Set-Location`（chdir），或使用 ASCII 引号路径；PowerShell 不支持 `&&`，用分号 `;`。

## 2. 项目定位与架构

新闻Daily 新闻与投资情报看板：

- **数据链路**：20个既定媒体入口的匿名列表与详情直采 → 来源/原始时间校验与去重 → 全部文章；脚本合格正文分别进入相关性筛选与独立摘要分类，分类结果回填全部文章，相关性及摘要分类均通过者进入Garena投资精选 → 公司/产品/融资 → 候选校验与统一发布。单条正文或模型失败隔离，不从全部文章删除合规元数据；公司新增只消费精选。所有来源不可用、整体模型不可用或发布校验失败保护旧网页。详见 `docs/architecture/UNIFIED_NEWS_PIPELINE.md`。feed 按真实承载页写来源类型，媒体名称相同不得视为公众号身份相同。
- **融资数据链路**：`snapshot.garenaSelected` 中的融资条目及对应私有正文 → `scripts/funding_table.py` → `data/funding/current.json` / `web/public/funding-table.json`；显式空精选不得回退全部文章或旧 feed。
- **前端**：`web/app/page.tsx` 渲染 `AppShell`，保留全部文章、Garena投资精选、公司与产品全景。前端设置页已删除，配置通过.env/Secrets管理；后台设置接口与独立服务保留兼容。AIHOT 专属日报/热点/API代理及 demo 回退已退役。旧公开历史/周报/审阅 HTML 和补录 JSON 只在候选中清理；`scripts/templates/` 保留为私有兼容渲染，不再发布旧新闻。
- **数据更新**：GitHub 定时为 UTC `30 1 * * *`（北京时间每天09:30）。校验本次run审计状态、event、ID、attempt及head SHA后，以created_at转北京时间最近已到达的09:30为截止点（09:30前创建取前一天），冻结此前24小时；创建时间无法可靠取得时在付费前停止。排队跨午夜及重跑不滑窗。手动默认启动时冻结rolling-24h，显式window-end与恢复沿原窗口。起点包含、终点排除；审核晋升后部署Pages，网页更新时间记录实际完成时刻。未恢复Codex定时跟进，真实schedule按NEXT_SCHEDULED_ACCEPTANCE清单验收。

## 3. 关键文件与所有权

| 文件/目录 | 归属 | 说明 |
|-----------|------|------|
| `scripts/build_snapshot.py` | 数据/后端 | 从已处理直采及兼容Manus结果构建 all/garenaSelected；兼容归档与私有模板渲染，不拉 AIHOT |
| `scripts/manus_source/`（client/config/contracts/pipeline/content_phase/crawler）、`scripts/enrich_news.py`、`scripts/llm_common.py`、`scripts/build_manus_feed.py` | 数据/后端 | Manus 采集与加工流水线（llm_common 自动加载项目根 .env；阶段 B 默认脚本爬虫，依赖 trafilatura） |
| `scripts/prompts/manus_discovery.md` | 数据/后端 | Manus 发现阶段 Prompt；含来源三元组、日期、顺序审计、计数重算及最终 JSON 自检 |
| `scripts/funding_table.py`、`data/funding/`、`web/public/funding-table.json` | 数据/前端 | 融资条目抽取、归档与前端表格数据 |
| `scripts/build_company_overview.py`、`scripts/company_index/`、`data/company-overview/` | 数据/前端 | 全类别公司/产品实体、增量合并、字段来源与调用预算 |
| `scripts/tag_news.py`、`scripts/eval_tagging.py` | 数据/后端 | AI 打标签 harness 与评测门禁 |
| `scripts/settings-server.mjs` | 工具 | 本地 API Key 设置服务（127.0.0.1:9731，写项目根 `.env`，保留后台/CLI兼容，前端设置页已删除） |
| `scripts/templates/*.template.html` | 数据侧渲染 | 静态快照模板（index/history/weekly） |
| `web/app/_components/`、`web/app/_lib/`、`web/app/api/` | 前端 | Next.js 组件、数据层、API 路由 |
| `data/archive/`、`scripts/retire_legacy_public.py` | 构建/迁移 | 归档来源清理与候选旧公开页面退役，禁止直接改正式 public |
| `docs/architecture/MANUS_DATA_CONTRACT.md`、`docs/operations/MANUS_SOURCE_RUNBOOK.md` | 契约文档 | 修改流水线前必读 |
| `tests/`、`web/tests/` | 全员 | Python 离线测试 + Node 前端/渲染/设置服务测试，改动后必须全绿 |

## 4. 常用命令（均在权威目录下执行）

```powershell
# 统一入口（doctor 不调用外部 API；dry-run 仅打印计划）
python scripts/run_pipeline.py doctor
python scripts/run_pipeline.py run --dry-run
python scripts/run_pipeline.py run --source-mode direct-only --dry-run
# 以下真实run可能调用付费服务，须处于已有授权范围
python scripts/run_pipeline.py run --source-mode direct-only --no-promote
# 手动明确复核固定窗口；GitHub定时按本次run创建时间冻结
python scripts/run_pipeline.py run --window-mode ten-am --date 2026-09-22 --cutoff-time 09:30 --dry-run

# 快照构建（幂等，可重复运行）
python scripts/build_snapshot.py

# 以下为已冻结窗口的分阶段兼容入口；新批次优先统一run
# 分阶段须沿用原NEWS_COLLECTION_END和MANUS_WORK_DIR，不能另取当前时间
python scripts/manus_source/runner.py --date 2026-08-27 --groups group_a group_b group_c
python scripts/manus_source/content_phase.py --date 2026-08-27
python scripts/build_manus_feed.py --date 2026-08-27
python scripts/funding_table.py

# 单账号来源校准：先离线审计，再显式允许一个 Lite 任务
python scripts/audit_manus_sources.py
python scripts/manus_source/runner.py --date 2026-09-10 --ten-am --account "机器之心" --allow-paid

# feed 校验但不晋升
python scripts/build_manus_feed.py --date 2026-08-27 --no-promote

# 全部离线测试
python scripts/test_pipeline.py offline
python scripts/test_pipeline.py llm-smoke --allow-paid  # 显式极小真实请求，每日最多一次
python scripts/test_pipeline.py llm-business-smoke --allow-paid  # 固定一条分类样本，每日最多一次
node web/tests/frontend/rendered-html.test.mjs
node web/tests/frontend/source-kind.test.mjs
node web/tests/settings/test_settings_server.mjs

# Next.js 前端
npm --prefix web run dev      # 本地 http://localhost:3000
npm --prefix web run build    # 构建（vinext 输出 dist/）

# 独立后台设置兼容服务（无前端设置页，仅监听127.0.0.1:9731）
node scripts/settings-server.mjs
```

- `runner.py --groups group_a` 只生成 group_a 发现结果。`content_phase.py` 与 `build_manus_feed.py` 仍按生产契约要求 group_a/group_b/group_c 三份发现文件齐全。
- `runner.py --account` 是隔离的单账号 canary：强制 Lite、创建不重试、最长 600 秒、异常请求停止、同账号同日一次。产物位于 `work/manus[/ten-am]/canary/`，不得复制到生产 raw 目录绕过三组契约。
- 若确需进行 group_a-only 全链路测试，可为未执行组生成明确的来源失败占位文件；这类 feed 会呈现 `degraded=true`，仅用于流程验证。未得到用户明确授权时使用 `--no-promote`，避免测试数据覆盖正式 feed。
- `MANUS_TIMEOUT_SECONDS` 默认值为 `3600`。长时间 discovery 任务不应再沿用 10 分钟上限。

## 5. Git 纪律（多 session 并行开发）

### 测试成本约束（用户于 2026-09-09 明确要求）

- 2026-09-10 用户更新授权：本次 DeepSeek 全量测试覆盖全部已扫描文章，不受下方小样本条数/费用上限限制；入口 `review_all_scanned.py --allow-paid`，成功缓存复用、失败保留并显式重试、输出隔离。Manus 仍控制成本；获取能力与完整24小时覆盖分别验收，样本获取成功即可记录能力通过，不能冒充全天完整覆盖。

- 公司官网补全每小样本最多5次；失败不自动重试，建议通过逐字引文校验后还需审阅，归属规则保存 config/company_research.json。品牌成立时间与团队不得直接覆盖母公司字段；保留品牌档案和新闻来源。

- 缓存新闻复核用 `review_cached_news.py`：付费请求前占位，摘要/公司抽取共用累计预算；默认8次，最多40次。同一输出目录仅运行一个进程。模型缓存按提示词版本区分，不能为了复用而把旧结果冒充新版本；人工修正保留独立记录。

- 默认 `python scripts/test_pipeline.py offline`，禁止回归测试调用真实付费服务。CI 的离线测试也使用该入口。
- 历史Manus探针规则（当前暂停，不执行真实HTTP）：检查 Manus key 使用 `manus-auth`，不要启动生产采集来确认密钥。只有必要的小样本实测使用 `manus-smoke --allow-paid`，当前工作区每天最多一次 Lite 创建尝试，不重试创建，观察 120 秒/最多 12 次轮询，观察到 20 credits 时请求停止。
- 检查 OpenAI-compatible 模型使用 `llm-smoke --allow-paid`：最多一次请求、输出上限 16 token、每天最多一次、不重试。它不验证新闻业务质量。
- 首次仅因结构化输出失败且代码已修复时，经用户明确授权可加 `--allow-retry-after-fix` 补一次；只接受同密钥/base/模型，第三次仍拒绝。
- 所有后续真实测试都先明确调用/任务上限与样本范围，并复用成功结果；认证失败、创建响应不确定或停止失败时先排查，禁止自动扩大范围或重复启动。
- 历史Manus运行规则（当前暂停，full已改映射direct-only）：当时统一 `manus-only` 入口按来源隔离、并发 3，默认每来源观察止损线 20 credits（可调 10..60）；`full` 仅是兼容别名。本次用户授权显式 `--manus-credit-limit 0`，仍走逐来源队列及终态保护，不能变成旧按组直连或取消余额熔断。已尝试的同窗口失败不自动重建。候选阶段成功不能代替内容质量及全窗口覆盖验收。
- 探针阈值不等于服务端硬性费用上限；生产入口不受探针台账限制，不能把 `--no-promote` 当作成本控制。细节与恢复见 `docs/operations/TESTING_COST_CONTROL.md`。
- 本地 `.env`、额度、完整响应及测试台账不入 Git；密钥不得出现在回复、CLI 参数、提交或文档中。

- main 分支直推；本地提交前先 `git pull --rebase`，避免与 CI 的新闻数据提交冲突。
- 若 CI 数据提交与本地分叉：优先重新生成受影响的数据产物后再提交，勿强推。
- 快照类提交使用 `chore: 更新新闻Daily 静态快照 [skip ci]`。
- 提交粒度参考 `docs/history/2026-08-17-manus-only-source-migration-plan.md` §5 的提交边界划分。
- 未经用户明确要求不得 push --force / reset --hard。

## 6. 硬性规范（用户明确要求，违反即返工）

1. **公众号原文链接（mp.weixin.qq.com）必须保留有效**，不得删改或禁用。
2. 不要重写页面、不改新闻数据、不加未经要求的新功能。
3. 公司档案日期用阿拉伯数字、保留证据精度；所有运行及刷新时间使用北京时间（Asia/Shanghai）。期刊日期展示用中文 numeral 格式（如“二〇二六年八月十四日”）；周报 VOL 标识格式 `VOL.2026·八月第 N 周`（周一为一周起点，按月内序号）。
4. 结构化字段（score、publishedAt、category 等）与 AI 叙事内容（摘要/标签）边界分明：UI 展示结构化字段，叙事内容只读消费。
5. 文档与代码必须同步修改：改流水线/契约时同步更新 PIPELINE.md、AGENT.md、README、DISTRIBUTE、使用说明。
6. 写作风格：避免使用先否定 X、再强调 Y 的对照句式（所有对话与文档）。
7. `config/accounts.json` 保留为扩容候选池（WeRead/搜狗已下线，勿恢复旧链路）。

## 7. 截图规范

- 全部截图集中存放在工作区根 `screenshots\` 目录。
- 新截图按功能模块 + 阶段命名，如 `history-archive-ui.png`、`nextjs-all-top.png`、`qa-stepN-xxx.png`。
- 勿再往根目录散落 png/jpg。

## 8. 交接文档体系

- `docs/maintenance/AGENTS.MD`（本文件）：开发守则。
- `docs/maintenance/CONTEXT.MD`：项目当前状态、实现进度、待办门禁，接手后第二份必读。
- `docs/maintenance/MEMORY.MD`：长期记忆与经验教训精编（按类别），供无记忆系统的 agent 使用。

候选审核入口为run_pipeline.py review-candidate / publish-candidate，操作见运行手册；必须保留审核来源和校验值，禁止修改旧state伪造重跑成功。沿用已确认业务规则，新增业务范围、信源、预算或发布行为须先具体说明并确认。


历史Manus队列规则（当前停用）：逐来源队列保持最多并发3；普通单来源失败不取消其他排队来源，余额不足、创建未知或远端停止未确认则保护性阻止新建。checkpoint及停止后只读回收仍过完整契约。`task.create` 的明确额度拒绝与未知创建分别记录；计划20源、发出POST数、成功取得taskId数及远端终态数必须分别汇报。不能把未创建来源说成不可达或无更新。2026-09-14的20 credits规则仍是默认观察止损，本次0阈值仅按本轮授权执行。

产品关系规则（2026-09-14确认）：仅开发／运营主体记为自有；集成、使用第三方产品保留为该公司的产品动态，按最新关联报道排序并保留日期、链接。productUpdates逐文章记录owned/integrated/used/unknown及引文，product_names兼容表示所有关联产品，不代表所有权。历史关联证据不足标关系待核实；纯论文、架构和算法方法不进产品库，可实际使用的开源工具保留。抽取提示词版本以 scripts/company_index/config.py 为准，旧缓存不伪装新版本。

2026-09-14新增确认：产品须可识别具体名称/型号，未具名集合和类别描述不入产品列表；新闻及公司主体保留。首页移除解释段和信源状态框，来源失败诊断仍存数据/运行报告。融资分类入口移至公司与产品全景，融资报道仍在全部资讯流。所有评分仅内部使用、不显示。抽取提示词版本以当前配置为准，旧缓存不改版本；reviewed research可用逐字官网证据确认ownershipEvidence，原报道日期/链接保持，集成方关系保持。未配置联网搜索时不得声称DeepSeek自动进行了网络检索。

2026-09-14用户确认：公司成立时间以法人注册日期为主；只有创立年份的历史值不冒充注册日期，展示时标明注册待核实。公司档案日期使用阿拉伯数字，保留原资料精度，不补造月日；此规则优先于上述期刊中文日期格式。
