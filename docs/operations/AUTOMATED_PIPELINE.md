# 自动数据流水线

2026-09-23 当前决定：暂时完全停用 Manus，统一使用既定媒体的网站直采及并行科技 DeepSeek-V4-Pro。`run_pipeline.py` 默认 `direct-only`，`full` 也是直采兼容别名；AIHOT 停用，GitHub 恢复北京时间每天 09:30 定时，保留手动运行；Codex 和本地定时跟进未恢复。`config/services.json` 在真实 HTTP 请求前禁止 Manus 和 Tavily，包括旧新闻发现、公司链接发现和相关探针。历史代码及原始结果保留供追溯。

具体来源、匿名读取限制与证据要求见[媒体页面直采](DIRECT_NEWS_COLLECTION.md)，文章两池及失败规则见[统一新闻链路](../architecture/UNIFIED_NEWS_PIPELINE.md)。所有命令从仓库根目录执行。

## 1. 检查与运行

本地按 `config/env.example` 配置 `.env`：`PARATERA_API_KEY`、`LLM_API_BASE=https://llmapi.paratera.com/v1`、`LLM_MODEL=DeepSeek-V4-Pro`。并行科技域名优先读取 `PARATERA_API_KEY`；旧 `DEEPSEEK_API_KEY` 可继续作为同一密钥的兼容变量。当前流程不需要 Manus 或 Tavily 密钥，也不回退其他模型服务。前端设置页已删除；直接管理 `.env` / 仓库 Secrets。独立后台设置服务、测试接口及 CLI 保留兼容，不提供设置 UI。

```powershell
python scripts/test_pipeline.py offline
python scripts/run_pipeline.py doctor
python scripts/run_pipeline.py run --dry-run

# 实际匿名采集及模型加工，保留独立候选
python scripts/run_pipeline.py run --no-promote
```

`doctor` 只检查本地配置、依赖、模型密钥是否存在和目录是否可写，不发外部请求、不输出密钥，不能证明余额或接口可用。`--dry-run` 只输出计划。实际 `run` 会读取媒体页面并调用模型；`--no-promote` 只阻止正式数据晋升，不限制调用。

GitHub 定时使用 UTC cron `30 1 * * *`（北京时间每天 09:30）。核对本次 run 的审计状态、event、run ID、attempt 与 head SHA 后，以 `created_at` 转北京时间最近已到达的 09:30 冻结截止时刻：09:30 前创建取前一天 09:30，之后取当天 09:30；窗口为此前 24 小时 `[start, end)`。`NEWS_COLLECTION_END` 贯穿各阶段，排队跨午夜或重跑不滑窗；创建时间无法可靠取得时，在采集与模型付费前停止。手动运行仍在启动时冻结 `rolling-24h`，可用含时区的 `--window-end` 显式指定；恢复沿原窗口。只接受原始发布时间，“昨天”发布的自然日例外及原始精度保留，不拿评论、更新时间或 URL 日期替代发布证据。本地 `ten-am --cutoff-time 09:30` 可显式复核固定窗口；`calendar-day` 保留历史兼容。

## 2. 当前阶段与输入

默认 `--stage all` 依次执行 `direct → news → snapshot → overview → funding`，来源采集最多并发 3 个。匿名列表仅提供候选，详情须通过来源身份、标题和原始时间核验。可访问、有合格样本、遍历了列表范围是不同结论，不能把部分成功称为 20 源完整覆盖。

| 阶段 | 当前职责 |
| --- | --- |
| `direct` | 按配置入口读取公开列表及详情；收据、原始响应和逐源状态留在私有 `inputs/direct/` |
| `news` | 全部合规元数据去重；合格正文独立摘要分类，相关性单独决定精选；生成 processed 与证据文件 |
| `snapshot` | `processed.json.allArticles` 对应全部，`items` 对应精选；不回填旧日报或旧 feed |
| `overview` | 仅精选文章抽取公司及产品，增量保留已有档案；随后处理已知网页资料补全 |
| `funding` | 仅精选融资文章及其 ID+URL 绑定的完整正文；当前不调用 Tavily 搜索 |

公开快照 `newsSelectionVersion=1` 下必须同时有 `all` 与 `garenaSelected`，空池合法、缺池错误。缺正文条仍在全部文章中显示“待正文”；有正文但不相关的文章照常生成摘要分类。单条模型失败单独标记，旧成功缓存不能冒充本轮新调用成功。

直采保留真实 `collector=direct_site`、`direct:` ID 和平台来源。schema3 feed 使用兼容路径 `data/manus/current.json`，目录名称不表示调用 Manus；旧 schema1/2 的 Manus 身份规则不放宽。全文只留私有输入，不写入公开 JSON。

公司抽取复用正文、模型及提示词版本匹配的成功缓存，处理本批全部精选；单篇失败写入 `articleFailures`，已有档案保留。产品区分自有、集成、使用和未知；纯方法、未具名集合与自然人不新造公司。人工修正使用独立证据绑定投影，不篡改成功缓存。最新报道时间与资料核验时间分开。

直采 overview 自动传入 `--known-link-research --research-full-review`。全量补全取消默认的每日 5 主体 / 10 页 / 5 请求上限，处理有限的缺资料主体队列；每主体最多 2 个已知网页，每个输入最多 1 次新模型请求。请求前占位、成功缓存复用、失败或不确定请求不自动重试、系统异常熔断均保留，不等于模型联网搜索，也不启动 Manus 寻链。默认小样本和历史恢复仍沿用原预算语义；云端账本无法证明可复用时仍保留同日运行归属和恢复门禁，可选补全延后不阻断主新闻链路。本地共享账本不受云租约约束。详见[公司资料补全](COMPANY_WEB_RESEARCH.md)。

## 3. 候选与失败恢复

每次新运行复制正式基线到 `work/runs/<date>/ten-am/<run-id>/workspace/`；`ten-am` 目录名用于兼容；窗口以本次冻结状态为准，不能从目录名推断定时或手动。候选包含 `data/manus/`、`data/archive/`、`data/cache/`、`data/company-overview/`、`data/funding/` 和 `web/public/`，私有输入另存 `inputs/`。

部分来源或正文失败允许其他核实文章继续；全部来源不可用、系统性模型失败、必需阶段或跨产物校验失败时保留正式旧版本。公司及融资新增严格只读精选，空精选不得回读全量或历史。程序成功不等于逐源无漏采或模型事实已全部人工确认。

`state.json` 保存冻结窗口、阶段状态、退出码、耗时和发布状态，`publication.json` 保存替换记录。`--resume` 沿原窗口和成功阶段恢复；代码、业务配置或模型上下文变更需新候选，不能改写旧指纹。同输入失败或不确定的资料补全请求不会因另起 run 自动重试。原始状态、正文和成功缓存保留供审计。

`work/pipeline.lock` 防止统一入口并发写入。强制中断留下的锁需确认原进程已结束后处理；独立旧 CLI 不受该锁管理，不能同时写正式产物。正式数据若被其他运行更新，旧候选不能覆盖新基线。替换使用目录备份及回滚日志，多个目录并非面向并发读者的全局原子事务；统一 Git 提交代表同一发布版本。

## 4. 审核并发布已有候选

以下命令只审核及晋升已有候选，不启动采集或模型：

```powershell
python scripts/run_pipeline.py review-candidate --candidate work/runs/<日期>/ten-am/<运行ID>/workspace
python scripts/run_pipeline.py publish-candidate --candidate work/reviewed-candidates/<审核返回的目录ID>
```

审核核对窗口、双池内容与包含关系、来源及去向计数、公司输入范围和跨文件一致性，并复制独立审核包。`review.json` 绑定来源 workspace、代码、候选文件及正式基线，类型为 `reviewed_import`，不改写采集状态。

发布重新校验并持有流水线锁；代码或候选变化需重新审核，正式基线变化需重建候选，较旧窗口不得覆盖较新窗口。发布只更新本地正式产物，后续提交及 Pages 部署需另行完成并核对线上 JSON。私有 inputs、正文、模型响应、台账和日志不提交。

## 5. GitHub 定时、手动工作流与恢复包

`.github/workflows/fetch-manus.yml` 文件名保留兼容，同时保留 `schedule`（默认 UTC `30 1 * * *`）与 `workflow_dispatch`，仅执行 all/direct-only。定时先校验 `schedule-audit` 的本次运行身份，再由 `scripts/automation/collection_window.py` 冻结窗口；审计失败或创建时间缺失则停止，不猜日期。手动页面 `window_end` 留空取启动时北京时间，另有 `date`、`promote` 和 `dry_run`。当前不提供 Manus、AIHOT 或 Tavily 运行选择。GitHub 可能延迟创建或排队，真实准点性必须另验；若平台跨日才创建，不能据冻结窗口倒推原本应触发的日期。

模型请求只使用仓库 Secret `PARATERA_API_KEY`，地址固定为 `https://llmapi.paratera.com/v1`，模型固定为 `DeepSeek-V4-Pro`；不通过变量或其他提供商密钥回退。恢复包密钥的兼容读取不代表启用对应付费服务。

工作流保存脱敏状态，并将原始页面、正文、模型缓存、研究台账和候选产物放入加密恢复包。恢复在新候选目录使用原缓存，缺失结果需明确处理，不能伪造旧运行成功或自动补付费请求。步骤见[加密恢复说明](PIPELINE_RECOVERY.md)。

成功提交并推送数据后，工作流以 `actions: write` 显式触发 `deploy-pages.yml`。派发成功只证明进入队列，最终还须核对 Pages 结果及线上 JSON；没有数据变化、未晋升候选或 dry-run 不触发该次部署。

## 历史流程说明

2026-09-22 前的 AIHOT/Manus 双源及其原09:30调度、Manus 逐篇 checkpoint 与 credits 止损、独立 feed/content 调试及公司 Lite 寻链均为历史流程，当前不执行。9月22日曾改为仅 Manus，9月23日再切换为当前网站直采并重新授权09:30调度；旧原始结果、收费记录和时间口径不改写，恢复时保持各自 schema 和来源身份。

- [9月14日部分来源验收](../history/2026-09-14/MANUS_PARTIAL_REVIEW_20260914.md)：partial 不等于完整窗口覆盖。
- [9月16日调度审计](../history/2026-09-16-SCHEDULE_AUDIT.md)：记录当时 schedule 延迟；当前直采定时须按[新验收清单](NEXT_SCHEDULED_ACCEPTANCE.md)另行验证。
- [9月18日审核补录](../history/2026-09-18-REVIEWED_ARTICLE_SUPPLEMENT.md)：记录旧独立补录方式，当前统一候选双池发布。
- [9月23日直采验收](../history/2026-09-23-DIRECT_NEWS_ACCEPTANCE.md)：直采证据、离线审校及发布状态分别验收。
