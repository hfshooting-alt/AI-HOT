2026-09-15更新：已获用户确认，统一每日overview阶段启用已知网页补全（--known-link-research），读取审核资料链接及当前公司相关新闻，最多检查5个主体/10页/5次DeepSeek请求，无新增Manus搜索。自动补空白字段标暂定、保留引文；不覆盖现有字段、不更改归属。按主体、模型和最新报道去重，同输入成功/失败均跳过；失败逐页/逐公司隔离，剩余队列后续轮次处理。新报道可再次触发。无新报道时不会主动轮询官网变化。

# 自动数据流水线

Manus只依据文章原始发布／发送时间收录，新增点赞、评论、互动、编辑或转载页面的刷新时间均不能使旧文章重新符合窗口。“昨天”等相对文字必须指文章发布，不得引用评论或互动时间。AIHOT批次不做这层原文时间拦截，先接收再进入相关性、摘要打标与公司更新流程；URL路径日期不作为发布时间判定。已确认的北京时间09:30窗口及“昨天”发布的自然日例外保持。

统一入口为 `scripts/run_pipeline.py`，命令从仓库根目录执行。原有分阶段 CLI 继续可用。日常操作优先使用统一入口，获取运行前检查、候选产物隔离、阶段记录与发布恢复。

当前完整链路与失败规则见[统一新闻链路](../architecture/UNIFIED_NEWS_PIPELINE.md)：AIHOT 与 Manus 独立并行采集，合并去重后统一模型加工；允许来源部分失败和单条隔离；完成合格新闻、公司更新及产物一致性校验后发布。

同一来源的已核实文章现在也可部分保留，逐篇checkpoint和止损回收规则见[9月14日验证记录](../history/2026-09-14/MANUS_PARTIAL_REVIEW_20260914.md)。partial不代表完整24小时覆盖，时间窗口保持09:30。

## 1. 先检查，再运行

公司库构建在实体合并后应用 `config/company_research.json` 的已审阅归属规则与缺失字段补全。只允许带核验时间、官网URL和引用的 reviewed 记录；品牌的团队、时间等保留在 brandProfiles，不能搬到母公司字段。外部字段来源 origin=research，与新闻原文 origin=article 区分。

来源费用阈值停止后，查看对应运行目录 `diagnostics/` 的任务ID与停止状态，再读取历史任务消息定位阶段。八个失败来源的对照复核见 [9月10日来源复核](../history/2026-09-10/SOURCE_DIAGNOSIS_20260910.md)。不要把浏览器入口可读等同于完整时间窗口采集成功。

后续测试统一遵循[测试成本控制](TESTING_COST_CONTROL.md)。默认先 `python scripts/test_pipeline.py`；确认 Manus 密钥用 `python scripts/test_pipeline.py manus-auth`。本页 `run` 生产命令会执行真实接口，`--no-promote` 不限制费用。

```sh
python -m pip install -r scripts/requirements.txt
python scripts/run_pipeline.py doctor
python scripts/run_pipeline.py run --dry-run --date 2026-09-07
```

`doctor` 检查配置、依赖、模板、必要密钥是否存在和输出目录是否可写；只创建随后关闭删除的临时探针，不调用外部接口，不输出密钥。它不能验证余额、密钥有效性和网络可用性。共享模型或公共配置缺项返回非零退出码；完整流程的 Manus 分支缺项仅令该分支不可用，其他来源仍可继续。

`--dry-run` 仅打印阶段及命令，不写数据、不调用接口，也不要求配置密钥。

有模型密钥但暂不使用 Manus 时，可以运行 AIHOT 及完整后续加工：

```sh
python scripts/run_pipeline.py doctor --source-mode aihot-only
python scripts/run_pipeline.py run --source-mode aihot-only --no-promote
```

`aihot-only` 的默认 all 流程依次运行 aihot、news、snapshot、overview、funding，只关闭 Manus。它保留 AIHOT 返回的各类文章，统一使用本站模型筛选和打标，再更新公司库与融资表；因此需要模型密钥，可能产生模型和可选 Tavily 费用（`--skip-search` 可关闭后者）。候选仍写入 `work/runs/`，方便先 review。旧单独 `--stage snapshot` 仍是无模型且排除公众号的调试入口，不代表每日完整流程。省略 `--no-promote` 会更新仓库正式快照。当前项目按公司内部 AI 情报用途使用 AIHOT；若未来改为收费、客户交付、代理接口、公开副本或对外批量再分发，再重新核对授权范围。

按 `config/env.example` 在根目录 `.env` 配置 Manus 与模型密钥。Tavily 搜索为可选。完成配置后：

```sh
# 实际采集和加工，生成候选产物；会调用外部接口并可能产生费用
python scripts/run_pipeline.py run --date 2026-09-07 --no-promote

# 检查候选产物后，复用成功阶段并发布
python scripts/run_pipeline.py run --date 2026-09-07 --resume

# 直接完成整套更新
python scripts/run_pipeline.py run
```

默认 `--window-mode ten-am`，`--date` 是窗口结束日。例如 `--date 2026-09-09` 固定覆盖 9 月 8 日 09:30（含）至 9 月 9 日 09:30（不含）。省略日期时取最近已经到达的北京时间09:30：09:30前取前一天，09:30及以后取当天。子阶段复用这个已确定的日期，排队延迟和加工耗时不移动窗口。跨日补跑需显式填写窗口结束日。

统一 full 入口现在逐来源创建发现任务，最多 3 个并发；默认每来源观察止损线 20 credits，可用 --manus-credit-limit 10..60 调整。20 个来源默认保留线合计 400 credits，实际消费可能因上报与停止延迟超出。创建不重试，费用报告保存在 work/manus[/ten-am]/<date>/cost-report.json，旧报告归入 cost-history。同窗口成功和失败结果默认都复用，显式 --retry-failed-sources 仅重试失败来源。已付费完成的模型结果会保存缓存；同窗口新候选继承缓存，不继承未审核新闻。

兼容旧数据的单阶段调试可用 `--window-mode calendar-day --date YYYY-MM-DD --stage snapshot`，含义仍为该自然日。原有 discovery/content/feed CLI 默认保留自然日模式，加 `--ten-am` 启用新窗口。旧三组文件与十点文件分开存储，不能混用。

固定窗口优先使用详情明确的 `published_at`；“昨天”按北京时间前一自然日全天纳入，保留日期精度和原始文字；其他不确定时间逐条隔离、来源标记覆盖缺口，不能把中午 12 点等虚构时间当作采集证据。快照的上游新闻也按同一窗口过滤新增入库；“AI 日报”独立同步 AIHOT 当日上午八点发布的成品日报，本站不再用十点新闻窗口冒充日报。周报、历史页、公司与产品库及融资表继续保留各自历史范围，热点榜仍是抓取时的榜单。归档保留与过期规则按实际运行时间执行，历史补跑不回拨网站时钟，窗口外已定稿历史保持不变；当前复核窗口按本次审核结果替换，避免被排除的新闻再次出现。

## 2. 阶段与输入

| 阶段 | 输出/前置要求 |
| --- | --- |
| `aihot` | 与 discovery 并行抓取 AIHOT，写入候选 inputs/aihot.json |
| `discovery` | Manus 发现三组账号的窗口文章，原始结果在 `work/manus/ten-am/<date>/raw/` |
| `content` | 读取同日三组发现结果，默认脚本提取正文；成功正文可复用 |
| `news` | 汇总成功来源，统一去重、模型筛选和摘要分类，生成 processed.json 与新 Manus feed |
| `feed` | 旧独立调试阶段：仅加工 Manus，使用原有严格发布门禁；不在新 all 流程中 |
| `snapshot` | all 流程只读取 processed.json 生成快照、归档、历史页及周报；旧单阶段命令仍自行采集合并 |
| `overview` | 扫描全部新闻类别，更新独立公司/产品库及逐字段来源记录 |
| `funding` | 从候选/既有快照和 feed 抽取融资表，可选搜索补全 |

默认 `--stage all` 并行执行 aihot/discovery，然后执行 content → news → snapshot → overview → funding。采集失败仍进入 news 校验和利用成功来源。`--stage <阶段>` 只运行旧独立阶段，不自动补齐前置阶段；aihot/news 由 all 编排。单独运行 content/feed 时需要同日期完整三组发现文件；overview/funding 至少需要一份有效快照或 feed。

Overview 按内容与版本复用成功抽取缓存。当前统一生产使用 `--require-complete --allow-partial`，覆盖全部输入，失败文章记录在articleFailures，保留已有档案；全部抽取失败才阻止发布。输入长度、并发及预算配置位于 `config/taxonomy.json → companyOverview`。每个公司字段在 `fieldSources` 保存值、原文 URL、文章 ID、来源和发布时间；同一公司按规范名与文章明确给出的别名合并。没有可靠依据的字段保留为空。

统一 news 阶段对本批次去重文章全部进行相关性处理，并对保留文章全部摘要分类，分别使用最多7200秒预算；单条未完成隔离并披露，全部失败才阻止发布，重试可复用缓存。旧单独 snapshot 的增量打标额度不再限制 all 流程。

Overview 收录有实质信息的公司及其产品；投资方、供应商和合作方有具体业务或投资事件也可收录，只有名字列举时不新增。行业按公司自身业务抽取。最新报道日期与资料更新日期分开，默认按报道时间排序。资料补全需要来源和核验时间。完整业务规则见[投资人验收口径](INVESTOR_ACCEPTANCE.md)。

`--skip-search` 跳过可选 Tavily 搜索。单组试采仍用原 CLI `python scripts/manus_source/runner.py --date YYYY-MM-DD --groups group_a`，下游生产契约继续要求三组结果。

## 3. 失败保护与断点恢复

每次新运行把既有产物复制到 `work/runs/<date>/ten-am/<run-id>/workspace/`（旧自然日模式没有 ten-am 层）。所有选定阶段成功后，再校验候选输出并替换对应正式目录：

- feed：`data/manus/`。
- snapshot：`data/archive/`、`data/cache/`、`web/public/`。
- overview：`data/company-overview/`、`web/public/`。
- funding：`data/funding/`、`web/public/`。

采集阶段失败允许继续利用成功来源；news 及其后续阶段失败时停止发布，正式产物保持原样，候选数据和缓存保留。`--no-promote` 运行各阶段自身校验并保留候选；最终跨产物一致性检查在发布时执行。

Overview 失败或待处理文章必须逐条记录articleFailures，计数不一致拒绝发布；历史公司继续保留，新报道补充字段、产品与来源。融资输入存在且全部抽取失败（含未完成任务）时拒绝覆盖旧表。旧独立 feed 的空结果门禁继续保留；新 all 流程允许显式缺失的 Manus feed，前提是至少一条来源完成或部分完成且存在共享加工合格结果。已核实零篇是合法结果，不等于失败。

```sh
python scripts/run_pipeline.py run --date 2026-09-07 --resume
```

恢复最近同日期运行时，保持原阶段和 `--skip-search` 选择。已成功阶段直接复用，失败阶段重新执行。发现阶段仅复用契约有效且全部来源成功的组；正文仅复用成功 URL；加工缓存仅复用 `complete`，旧 fallback 会重新尝试。同 URL 的后续成功正文优先于历史失败记录。

代码、业务配置或模型名/接口地址/正文模式发生变化会拒绝恢复，要求新建运行。密钥值不进入签名，可补齐或更换。若正式产物已被其他运行更新，旧候选不得覆盖较新的数据。

发布使用目录备份和日志：异常时回滚；进程被强制终止后，下次同次运行的 `--resume` 恢复未完成发布。多个目录的替换不是面向并发读者的全局原子事务；Git 提交后的整套文件才是同一发布版本。

`work/pipeline.lock` 防止统一入口并发写入。强制终止可能留下锁；先确认没有运行中的流水线，再处理残留锁并恢复原运行。单阶段原 CLI 不受此锁管理，勿与统一入口同时写入正式产物。

## 4. 日志与溯源

`work/runs/<date>/ten-am/latest.json` 指向最近十点运行，旧自然日模式使用 `work/runs/<date>/latest.json`。每次运行的 `state.json` 保存固定 collectionWindow、阶段、状态、退出码、耗时和发布状态；`publication.json` 记录目录替换状态；`backup/` 保留发布前版本。运行目录和原始正文在 Git 忽略范围内，不会自动清理，磁盘维护时确认运行完成后按日期归档或移除。

正式数据失败时保留旧版本，因此应结合运行状态判断更新是否完成，不能只看页面能否打开。运行状态不含密钥或正文；排错时避免分享 `.env` 或原始全文。

## 5. GitHub Actions

`.github/workflows/fetch-manus.yml` 每天北京时间 09:30（UTC 01:30）开始全流程，测试通过后调用统一入口，成功后将整套正式数据提交到仓库；并非09:30整完成更新。GitHub schedule 可能延迟，不能保证准点。手动输入为 `date`（窗口结束日）、`stage`、`promote`、`dry_run`、`skip_search`；可选阶段为 all/snapshot/overview/funding。独立 content/feed 所需原始正文未存入 Git，所以这两个阶段仅在保留原始文件的本地运行。

默认 `full` 模式需要 GitHub Secrets `MANUS_API_KEY`、`DEEPSEEK_API_KEY`；可选 `TAVILY_API_KEY`，模型接口和模型名可用 Variables `LLM_API_BASE`、`LLM_MODEL`。手动任务可选 `source_mode=aihot-only`，仅关闭 Manus，仍读取模型及可选搜索密钥，运行完整下游。定时任务仍默认执行 `full`。如果修改 taxonomy 中 `api_key_env`，同步工作流的密钥注入。

工作流只上传 `state.json`，保留 7 天。原始结果、正文、候选产物和密钥不上传。CI 作业之间暂不支持断点续跑；本地保留 work 目录时可以恢复。失败查看 Actions 日志与状态 Artifact。

这条任务更新仓库数据后触发 Pages 静态发布。离线样本测试证明编排和保护机制；全账号采集与自动发布衔接仍需一次真实 CI 验收。

## 2026-09-10 Pages 发布衔接

每日工作流提交正式数据并成功推送 main 后，使用 GitHub CLI 显式触发 `deploy-pages.yml`。工作流需要 `actions: write`；沿用内置令牌，不新增个人令牌。没有数据变化、候选运行或 dry-run 不触发此次发布。触发成功只表示部署已排队，最终结果仍须检查 Pages 工作流。GitHub 内置令牌的 push 不会自行触发另一个 push 工作流。


2026-09-10 更新：统一入口默认 `--cutoff-time 09:30`，通过 `AIHOT_CUTOFF_TIME` 传递到全部子阶段；`ten-am` 参数及目录名保留兼容，不表示实际时刻。旧独立 CLI 默认十点，复现旧窗口使用统一入口 `--cutoff-time 10:00`。窗口改变会改变恢复指纹，旧窗口缓存经契约检查不会作为新窗口采集结果复用。首次提前半小时会与旧批次重叠半小时，按文章标识/链接去重。

完整管线的公司库阶段强制 `--require-complete`，复用成功抽取缓存，处理全部未缓存输入文章（包括 all 池）；单条失败或延后写入隔离清单，合格结果继续；全失败才保留旧网页。公司资料按新文章增量更新，最新提及置顶；没有证据的字段保持空白。审阅过的归属和分类自动应用，产品归属未明时保留 pendingEntities。AIHOT-only 只关闭Manus，仍运行共享模型与公司更新。每日快照写入 publicationMode=pipeline，首页仅展示该完成批次。

完整 full 模式同时要求 `--require-tags`，当轮归档池的未分类或fallback条目必须完成模型分类；失败缓存可重新处理，已成功缓存继续复用。异常时只保留候选目录，不提交网站数据。所有成功表示程序与结构化覆盖检查通过，不等同于所有信源无漏采或模型事实绝对正确。

本轮后续修正见 docs/history/2026-09-14/QUALITY_CORRECTIONS_20260914.md：新闻分类与产品归属独立，个人产品保留pendingEntities并展示；已核实旧闻逐条隔离，未泛化为全网原文时间已验证。

## 审核并发布已有候选（不调用采集或模型）

```powershell
python scripts/run_pipeline.py review-candidate --candidate work/quality-corrected-20260914/workspace
python scripts/run_pipeline.py publish-candidate --candidate work/reviewed-candidates/<审核返回的目录ID>
```

第一步校验窗口、新闻集合与内容、收录去向计数、公司处理范围和跨文件一致性，复制成独立审核包。review.json记录真实来源workspace、代码校验值、候选文件校验值和正式数据基线，类型为reviewed_import；不改写原采集运行状态。
第二步重新校验并持有pipeline.lock，候选或代码发生变化需要重新审核；正式数据变化需要重建候选。较旧窗口不能覆盖较新正式窗口。写入采用既有备份与回滚机制，重复发布已完成记录不会再次覆盖。中断记录保留供排错，不能伪造成功状态。

发布只更新本地整套正式产物；之后提交data和web/public到main，Pages工作流构建部署。私有inputs、review.json、正文及日志仍在work，不提交。

信源status保持complete/partial/failed/not_requested契约；公开reasonCode区分not_started_budget（熔断后未创建）、budget_stopped（已启动后止损）、boundary_unverified（未扫完窗口）、content_incomplete（部分正文缺失）等。只输出白名单原因码，不把原始错误或密钥带入网页。缺少证据时显示原因待核实。


用户于2026-09-14确认：最多并发3个来源，普通单来源费用止损不再取消其他排队来源，全部来源依次获得启动机会。每来源20 credits观察止损和已核实文章checkpoint／停止后只读回收保持。已实际尝试的同窗口失败结果不自动付费重试；明确标记task not created的旧熔断占位不算一次尝试，允许首次启动。余额不足、无法确认远端任务停止等系统性异常仍保留保护，不能保证异常或作业超时情况下全部完成。
