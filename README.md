# 新闻Daily

新闻Daily 通过匿名媒体页面直采获取新闻，统一使用并行科技 DeepSeek-V4-Pro 加工，提供“全部文章”、“Garena投资精选”和“公司与产品全景”。Manus 暂停，Tavily 停用，服务开关在 `config/services.json`，旧入口也在HTTP前阻断。直采运行及证据边界见[媒体页面直采](docs/operations/DIRECT_NEWS_COLLECTION.md)。AIHOT 采集、日报、热点、实时接口和演示内容回退已停用。现有仓库名称及 [GitHub Pages 部署路径](https://hfshooting-alt.github.io/AI-HOT/) 保留兼容。

“全部文章”保留本批通过来源、原始发布时间校验并去重的文章元数据。按用户2026-09-23确认的规则，所有合格正文独立生成摘要和分类，不以 AI 相关性通过为前提；非精选文章也可有分类，非 AI 内容不强制填写 AI 维度。缺正文显示“待正文”，不能凭标题分类；单条打标失败明确显示状态，标题、来源、时间和原文链接仍可阅读。“Garena投资精选”继续单独执行实质 AI 相关性、摘要与分类校验。公司、产品及融资新增只消费精选，显式空池不从历史或旧 feed 回填。私有完整正文不进入网页。

独立打标修复与旧批次补处理已完成，历史诊断见[技术记录](docs/architecture/UNIFIED_NEWS_PIPELINE.md#2026-09-23-独立打标调整)。当前批次结果以公开JSON及维护上下文为准。

GitHub 定时使用 UTC cron `30 1 * * *`（北京时间每天 09:30）。核对本次 run 的审计状态、event、run ID、attempt 与 head SHA 后，以 `created_at` 转北京时间最近已到达的 09:30 冻结截止时刻：09:30 前创建取前一天 09:30，之后取当天 09:30；窗口为此前 24 小时 `[start, end)`。`NEWS_COLLECTION_END` 贯穿各阶段，排队跨午夜或重跑不滑窗；创建时间无法可靠取得时，在采集与模型付费前停止。手动运行仍在启动时冻结 `rolling-24h`，可用含时区的 `--window-end` 显式指定；恢复沿原窗口。原始发布/发送时间是唯一绝对时间依据，编辑、评论及互动不让旧文章重新入窗。既有“昨天”发布例外保留前一自然日精度和原文证据，不补造时分，且不代表严格 24 小时完整覆盖。完整规则见[统一新闻链路](docs/architecture/UNIFIED_NEWS_PIPELINE.md)。

## 本地启动

需要 Node.js >=22.13.0、Python >=3.10。所有命令从仓库根执行：

```sh
npm --prefix web ci
python -m pip install -r scripts/requirements.txt
npm --prefix web run dev
```

前端设置页已删除；按 `config/env.example` 手动配置根目录 `.env`，GitHub 使用仓库 Secrets。独立 `scripts/settings-server.mjs`、后台设置接口与 CLI 保留兼容，不提供设置页。仅查看已发布快照无需付费接口。密钥、完整正文、模型响应及费用账本保存在私有位置，不提交。

## 采集、候选与发布

已恢复 GitHub 每天北京时间 09:30 的定时入口，并保留手动运行；未恢复 Codex 或本地定时跟进。实际触发及发布仍需[真实定时验收](docs/operations/NEXT_SCHEDULED_ACCEPTANCE.md)。统一入口默认 `direct-only`，`full` 同样映射到直采；`--no-promote` 生成隔离审核候选。显式 `manus-only` 暂停，`aihot-only` 仍被拒绝。20 个新闻信源来自 `config/manus_sources.json`，最多并发 3 个。合格文章继续处理；单来源失败不等于窗口内没有更新。

```sh
python scripts/run_pipeline.py doctor
python scripts/run_pipeline.py run --dry-run
python scripts/test_pipeline.py offline
npm --prefix web test
```

实际 `run` 的新闻与公司模型处理会产生并行科技 API 费用；`--no-promote` 只隔离输出。用户已授权完整处理本批文章和公司资料队列，直采默认启用 `--research-full-review`，不再被原5主体/10页/5模型的日额度截断。每个资料输入最多2个已知网页、1次新模型请求，成功缓存复用、失败输入不自动重试、系统性异常仍熔断；完整账本保留。此授权没有恢复 Manus。

网页读取和模型加工分别留证。获取入口可达、窗口内取得样本、完整窗口覆盖须分别验收；列表分页和转载延迟造成的覆盖缺口不会因增加模型调用自动解决。

候选生成后统一核对新闻、公司、融资、来源状态及隐私边界；通过 `review-candidate` / `publish-candidate` 发布已有候选不会重新调用模型或创建任务。运行与恢复步骤见[操作说明](docs/operations/AUTOMATED_PIPELINE.md)。Pages 部署读取发布后的整套 JSON，最终是否上线以数据提交和 Pages 结果为准。

手动复核固定时间批次可显式使用 `--window-mode ten-am --date YYYY-MM-DD --cutoff-time 09:30`；日常手动运行仍默认滚动 24 小时。GitHub 定时截止点由本次 run 创建时间冻结，不取 runner 开始工作的日期。

## 前端与公开资源

前端读取 `snapshot.json` 的独立 `all` / `garenaSelected` 两池，识别 `direct:` 及历史 `manus:` 条目。空池保持空；快照缺失或坏数据显示错误，不追加旧日报、周报、实时新闻或浏览器补录。公司库与融资表分别读取 `company-overview.json`、`funding-table.json`。

迁移旧公开页面时，只在候选 workspace 中执行：

```sh
python scripts/retire_legacy_public.py --workspace work/<candidate>/workspace
python scripts/retire_legacy_public.py --workspace work/<candidate>/workspace --apply
```

默认先列清单，随后可显式清理；必需 JSON 内容不由该脚本修改。历史/周报 HTML、旧审阅页和浏览器补录会退役，审核清单写在候选根目录。额外公开状态 JSON 需核验后逐项 `--keep path.json`。清理后仍须完成常规候选校验，不直接修改正式 `web/public/`。

| 命令 | 用途 |
| --- | --- |
| `npm --prefix web run dev` | 本地网页 |
| `npm --prefix web run build` | 生产构建 |
| `npm --prefix web run build:pages` | 生成静态站点，不调用付费 API |
| `npm --prefix web test` | 构建及 Node 回归 |
| `npm --prefix web run typecheck` | TypeScript 检查 |
| `python scripts/test_pipeline.py offline` | 禁止网络及付费请求的 Python 回归 |
| `python scripts/run_pipeline.py run --dry-run` | 只查看阶段与费用相关参数 |
| `python scripts/run_pipeline.py review-candidate --candidate work/<candidate>/workspace` | 校验已有隔离候选 |

## 公司资料与证据

公司抽取只使用本批精选与其私有正文。产品区分 owned / integrated / used / unknown，通用技术方法不能当产品；国家和法人日期须有来源，单轮融资、市值、历史估值不能混填。原始新闻日期与资料核验日期分别保存。

来源迁移清除仅由 AIHOT 支撑的新闻和字段，不凭空重算成功缓存。经审核的历史媒体和独立官网证据保留，已有费用/研究账本不重置。资料补全按待处理队列执行，逐字段证据规则保持；未知官网不会靠模型记忆补造，暂缺字段继续明确缺失。详见[公司资料操作说明](docs/operations/COMPANY_WEB_RESEARCH.md)和[公司数据契约](docs/architecture/COMPANY_OVERVIEW_CONTRACT.md)。

## 目录与维护

- `web/`：前端源码、构建配置、公开资源和 Node 测试。
- `scripts/`：采集、正文、新闻模型、公司融资、候选审核与发布工具。
- `config/`：生产信源、分类、审核规则和环境样例。
- `data/`：正式业务产物、归档与成功缓存；`work/`：私有输入、候选、响应和审计。
- `tests/`：Python 离线回归；`docs/history/`：原始历史记录，不作为当前运行状态。

开发前阅读 [AGENTS.MD](AGENTS.MD)、[当前状态](docs/maintenance/CONTEXT.MD)和[维护经验](docs/maintenance/MEMORY.MD)。模块入口见[代码导航](docs/architecture/CODEBASE_GUIDE.md)，来源字段与时间规则见[Manus 数据契约](docs/architecture/MANUS_DATA_CONTRACT.md)，完整文档见[文档入口](docs/README.md)。
