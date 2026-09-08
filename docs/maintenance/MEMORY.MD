# docs/maintenance/MEMORY.MD — AI HOT 长期记忆与经验教训精编

> 供接手 agent 快速吸收历史结论，避免重复踩坑。按类别组织。最近同步：2026-09-08。

## 1. 信源架构（已定论，勿走回头路）

- **当前唯一公众号信源 = Manus**（`scripts/manus_source/`）。`config/manus_sources.json` 是唯一账号配置源，现有 20 个账号：group_a 7、group_b 7、group_c 6。搜狗与 WeRead 链路已于 2026-08-17 迁移时删除；`config/accounts.json` 仅作扩容候选池保留。
- **aihot 第三方 API**（`https://aihot.virxact.com`）：提供日报、周报、热度榜和 `score` 字段。`selected` 字段实测全为 true，高分筛选使用 score ≥75。
- 分页参数存在，信源本身仍有结构性限制。公众号扩容遵循“验证一个、迁入一个”，不得恢复搜狗或 WeRead 旧链路。

### 搜狗路线的历史结论（下线原因，供参考）

- 约 100 次请求后容易出现验证码；39 账号高频抓取会稳定触发频控。
- `type=1` 账号检索已衰败，跳转链依赖易碎的 JS 拼接，`tsn` 时间过滤无效，公众号账号 ID 缺失。
- 文章缺失由索引滞后与规模化频控共同造成，降速和增量合并只能缓解。

## 2. 历史回溯系统设计要点

- `data/archive/YYYY-MM-DD.json` 是日报、周报和历史视图的统一归档源；upsert 幂等，wechat/manus 条目用 `(账号名, 标题)` 作为稳定键。
- finalize 边界：前天及更早才固化，昨天保持开放以接纳迟到条目；cleanup 删除 30 天前归档与历史页，周报保留最近 5 期。
- 自然周以周一为起点；VOL 标识格式为 `VOL.2026·八月第 N 周`；日期由 `fmt_cn_date()` 输出中文数字。周报生成循环应在“整周早于最早归档日”时退出。
- 冷启动归档起点为 2026-08-07，首期八月第 1 周只有 3 天数据，属于预期。

## 3. Manus 流水线、契约与真实稳定性

- 正式链路：discovery → content（默认本地 `crawler.py` + trafilatura；可切换 Manus）→ `enrich_news.py` 摘要/分类/标签 → `build_manus_feed.py` 全量校验 → 原子晋升 `data/manus/current.json` → `build_snapshot.py` 归档和快照。
- `scripts/funding_table.py` 在 feed 晋升后抽取融资字段，可选 Tavily 补全，产出 `data/funding/current.json` 和 `web/public/funding-table.json`。
- 正文批次由 `validate_content_batch` 检查风控、跳转、过短和标题漂移。全文与密钥不得进入 feed、诊断 Artifact 或 Git。
- 修改流水线前必读 `docs/architecture/MANUS_DATA_CONTRACT.md` 与 `docs/operations/MANUS_SOURCE_RUNBOOK.md`。

### Manus 任务成功与契约通过

- Manus API 返回成功或 structured output 只说明平台完成任务并返回对象。本地仍需校验字段身份、日期、来源审计、计数、枚举和 JSON 根结构。
- Prompt 加固前遇到过三类真实问题：
  - 白鲸出海返回 `account_name=null`，并把“白鲸出海”写入 `source_platform`；
  - 极客公园的 `source_audits.article_count=4`，最终 `articles` 只有 3 条；
  - 文章 URL 含 `20260825`，返回的 `published_date` 却是 `2026-08-26`，属于契约之外仍需关注的数据质量信号。
- 根因包含两层：早期 Prompt 对来源常量、计数重算和提交前自检约束不足；Manus 执行长链路浏览任务时具有概率波动。加强 Prompt 能显著收紧输出，无法保证每次都稳定通过，因此本地契约必须保留强校验和拒绝晋升机制。
- `da51733` 已在 `scripts/prompts/manus_discovery.md` 增加：来源三元组逐字复制、白鲸出海正反例、complete 字段完整性、按最终文章重算 `article_count`、每个配置来源恰好一条 audit、failed 来源规则、根字段白名单和最终 JSON-only 自检。

### 超时与分组测试

- `MANUS_TIMEOUT_SECONDS` 默认值为 3600 秒。discovery 常会超过 10 分钟，客户端超时应保留一小时；GitHub Actions 作业上限当前为 240 分钟。
- `runner.py --groups group_a` 只负责 group_a discovery。`content_phase.py` 与 `build_manus_feed.py` 会读取三组发现文件，缺组时拒绝继续。
- 2026-08-25 至 27 的 group_a 测试为未执行的 B/C 生成了明确失败占位，因此 feed 的 `configuredAccounts` 仍为 20，complete 仅 3–4，failed 为 16–17，`degraded=true`。
- 这类占位适合验证 discovery → snapshot 的机械链路。它会混合“未执行”和“真实失败”两种统计，不能用于评价全账号覆盖率；常规试跑应使用 `--no-promote`。
- 三日测试最终发布 4、6、3 篇，fallback 均为 0，证明当前链路可完成更新、晋升和归档。后续仍需重复运行及三组全量测试来评估 Manus 稳定性。

### 既有契约经验

- `schema_version` 是本地契约版本号。Manus 作为通用执行器不负责理解该字段；`runner.py` 在落盘校验前权威写入 `DISCOVERY_SCHEMA_VERSION`，校验端继续强制检查。
- 曾有 `build_item` 把 `manus:*` ID 包成 `aihot:manus:*` 的问题，已修复并加回归测试。
- 腾讯 news.qq.com/rain 与网易 163.com/dy 页面可由本地脚本静态抓取；家庭网络曾实现 15/15 成功。CI 数据中心 IP 仍需真实验证。
- 跳转漂移比较 host/path，忽略 query；标题一致性采用去除空白后的双向子串，兼容站点后缀和空格差异。

## 4. 分类、前端与部署

- 分类体系现为六类：融资动态、深度访谈、产品和模型发布、论文研究、大厂动态、泛行业新闻。结构化字段由 UI 直接展示，摘要和标签作为只读叙事内容消费。
- 融资动态使用独立 `FundingTableView`、专属枚举、来源列和筛选；数据生成由 `funding_table.py` 负责，Tavily key 缺失时字段留空，不阻塞主 feed。
- 技术栈：Next.js 16 + React 19 + Tailwind 4 + vinext + Drizzle + Wrangler。`web/app/` 是当前前端主形态，线上发布切换仍待完成。
- aihot API 没有结构化来源类型字段；公众号、推文、资讯和一手信源由 `web/app/_lib/display/source.ts` 依据域名和来源名判定。公众号范围包含 Manus 条目与 aihot 公众号条目。
- “全部 AI 动态”需合并 API 池和 `web/public/snapshot.json` 池，才能显示 Manus 条目。
- 仓库当前只有 `fetch-manus.yml`，通过 `run_pipeline.py` 更新 Manus feed、快照、历史/周报、缓存和融资表；全部阶段成功后发布并提交。Next.js 托管部署仍待接通。
- CloudBase 固定地址为 `https://david-d5gb2azg2557337ab-1457311474.tcloudbaseapp.com/`。覆盖静态文件后需考虑 CDN 缓存。

## 5. Git 与协作纪律

- 多 session 并行开发时，提交前先 `git pull --rebase`；与 CI Manus 数据提交冲突时重新生成受影响产物后提交，禁止 force push。
- 状态文档以已提交 `main` 为基线。本地修改、未跟踪诊断文件和临时 worktree 需通过实时 `git status` 单独确认，不能写成正式能力。
- 改动按 feat、fix、docs、chore+[skip ci] 拆分。代码、契约、Prompt 和数据产物应保持清晰提交边界。
- 本地修复完成后需确认远端 CI 使用的新 commit，防止线上持续运行旧代码。

## 6. 常见坑（高频复发，重点防范）

| 坑 | 对策 |
|----|------|
| Manus 任务成功但契约失败 | 保留上一次 `current.json`，检查 structured output 的来源三元组、audit 覆盖、字段完整性和计数；不得绕过契约直接晋升 |
| `article_count` 与最终文章数不一致 | 以最终 complete articles 按账号重算；排除的候选不得计入 audit |
| 账号字段互换或为空 | `account_name`、`source_platform`、`source_home_url` 必须从同一配置项逐字复制，禁止使用页面显示值替换 |
| group_a-only 直接进入正文阶段 | 下游固定要求三组文件；常规试跑停在 discovery，或使用明确失败占位并执行 `--no-promote` |
| 10 分钟 discovery 超时 | 保持 `MANUS_TIMEOUT_SECONDS=3600`；诊断时区分平台执行耗时与客户端等待上限 |
| 契约通过但混入模板页 | 契约解决结构完整性，业务有效性需独立过滤；重点识别占位标题、模板正文和非新闻内容 |
| 测试污染 `web/public/snapshot.json` | 快照测试必须传 `--snapshot-json` 到临时目录；全量测试后核对该文件未变化 |
| Windows 沙箱临时目录不可写 | 使用 `tests/_tempdir.py::make_temp_dir`，避免权限过严的 `tempfile.mkdtemp` |
| Windows 下 Node/Vite 出现 spawn EPERM | Node 测试可逐文件直接执行；vinext 构建需要合适权限 |
| npm 脚本的类 Unix 环境变量前缀在 Windows 无效 | 已统一使用 `scripts/vinext.mjs`，保留跨平台入口 |
| fallback 摘要过短或 LLM 摘要超过 220 字符 | 改进确定性摘要段落选择，并在 Prompt、重试、截断或上限之间明确策略 |
| Shell 内联中文路径被控制台编码破坏 | 先切换到目标目录；避免在命令字符串中重写中文内容，文档编辑统一使用可靠补丁工具 |
| Python `re.sub()` 替换串解释转义序列 | 使用函数替换形式 `lambda m: text` |
| Git rebase 在非交互环境等待编辑器 | 设置 `GIT_EDITOR=true` |

## 7. 用户偏好（必须遵守）

- 公众号原文链接必须保留有效；不重写页面、不改新闻数据、不加未经要求的新功能。
- 避免使用先否定 X、再强调 Y 的对照句式，适用于对话与文档。
- 日期展示使用中文 numeral 格式；周报 VOL 使用 `VOL.2026·八月第 N 周`，周一为一周起点。
- 用户于 2026-09-08 授权完善定时数据更新与失败保护；收藏/待讨论标记和每周 Word 周报归档仍属于待确认规划。
- 已确认决策：正文默认由本地脚本爬虫获取；“公众号”筛选包含 Manus 与 aihot 公众号条目；来源类型使用域名与来源名启发式；工作区中的 `ai news url crawler_20260810` 原型目录不改动；状态文档以已提交代码为基线。

## 2026-09-08 目录维护约定

- 新组件按 layout/views/news/funding/reports/shared 分工，数据工具按 data/domain/display 分层。
- 当前三份业务配置仅维护 `config/` 中的一份；CLI 默认路径已跟随迁移。根目录 `.env` 与既有数据/缓存位置保留。
- 文档从 `docs/README.md` 进入；旧设计计划集中到 `docs/history/`。精确旧新路径查 `docs/architecture/PATH_MIGRATION.json`，单文件历史用 `git log --follow -- <新路径>`。
- Python 测试集中在 `tests/pipeline/`，保留 `__init__.py` 确保递归发现全部 169 项。

## 2026-09-08 自动化维护约定

- 日常操作使用 `scripts/run_pipeline.py`；阶段实现继续维护在原业务模块。`--dry-run` 无接口调用，`--no-promote` 仍执行真实接口并保留候选。
- 只缓存并复用成功正文、完整 enrichment；fallback 和失败应重试。发现恢复只复用全来源成功且契约合法的组。
- 融资全部抽取失败与真实无公司必须区分；前者不能覆盖旧表。feed 的来源失败/正文失败导致空列表同样拒绝发布。
- 候选产物位于 `work/runs/`，正式更新前验证与检查原数据是否变化。异常回滚通过目录备份和 publication.json 完成，多目录不具备并发读取的全局原子性。
- 本地断点恢复需要同次运行文件和未变的代码/配置。CI 只上传状态，不上传原文，暂不支持跨 CI 作业恢复。
- 快照测试固定时钟，并替换所有外部抓取（包括 hot API），避免时间变化或网络故障影响离线回归。
