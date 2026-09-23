# 公司资料联网补全

2026-09-23 当前流程：网站直采精选关联主体及既有缺资料主体 → 读取已知网页 → 并行科技 DeepSeek-V4-Pro 提议 → 引文与字段口径校验 → 暂定空白字段／候选归属 → 候选校验及统一发布。暂时完全停用 Manus，Tavily 同样停用；`config/services.json` 在真实 HTTP 前执行开关。没有已知可读页面时保留空白，不能解释为已经全网搜索。

## 入口与模块

统一入口 `scripts/run_pipeline.py` 默认 `direct-only`，`full` 同样指向直采；overview 阶段传入 `--known-link-research --research-full-review`，不传 `--discover-company`。单独公司构建的 `--known-link-research` 默认仍为小样本，只有再显式加 `--research-full-review` 才取消原每日上限。全量参数不能与 `--discover-company` 合用。`--no-promote` 仅阻止发布，不能阻止模型调用；定时仍关闭。

本地并行科技域名优先读取 `PARATERA_API_KEY`，旧 `DEEPSEEK_API_KEY` 可承载同一密钥作为兼容变量。GitHub 仅使用 Secret `PARATERA_API_KEY`，固定 `https://llmapi.paratera.com/v1` 与 `DeepSeek-V4-Pro`，不回退其他模型提供商。

[公司模块导航](../../scripts/company_index/README.md) 说明各处理职责。审阅规则保存在 config/company_research.json；补全记录和候选归属随公司 JSON 发布，完整响应与台账留在忽略目录 work/。

## 当前全量补全与默认小样本

用户已允许充分使用现有并行科技模型 API；当前直采开启的 `--research-full-review` 不再受每日 5 主体 / 10 页 / 5 模型请求限制。它处理本次有限的缺资料主体队列，每主体最多 2 个已知网页，每个输入最多 1 次新模型请求；报告列出队列大小、实际页面数、请求数与未处理原因。它不扩展到自动搜索新链接，也不是让模型自行联网检索。

全量模式继续使用稳定私有账本，请求前预留、同输入成功结果复用、失败或状态不明不自动重试、系统性异常熔断。原缓存与历史占位不清零，成功建议回放不刷新资料日期。云端保留已有同日运行归属租约及恢复门禁：新 runner 未恢复私有账本且已有其他 run 占位时，可选资料补全 defer，主新闻和公司抽取继续。本地共享账本不受云租约约束；解除每日财务上限不等于解除跨运行重复调用保护。

下表是**未开启全量参数的默认小样本及历史恢复语义**，不限制当前已授权的直采全量队列：

| 步骤 | 范围与上限 | 失败处理 |
| --- | --- | --- |
| 历史 Manus 链接发现（当前停用） | 旧上限为每天 1 个主体、Lite、20 credits 观察止损；只保留旧记录 | 当前服务开关拒绝真实请求，不随全量补全重新启用 |
| 原页读取 | 北京时间实际执行日最多 5 个主体、10 个页面；每主体最多 2 个链接，读取前持久预留 | 单页失败隔离，同主体其他页继续；失败预留不退回 |
| DeepSeek 补全 | 同一实际执行日最多 5 次请求，请求前持久预留，仅补缺失字段 | 成功结果保存后可离线回放；超时、失败和状态不明不自动重试 |

历史公司搜索与新闻媒体采集费用分开，20 credits 是当时的观察止损线，不是服务端硬上限，当前不创建该任务。已知链接按主体、模型、链接及最新报道去重，同输入成功／失败均跳过，新报道可形成新输入。没有新报道时不会主动巡检官网变化；无可用页面和异常后的余项仍可延后，不保证当日补齐全库所有字段。

基本资料（主营业务、国家、法人注册日期、团队）与待归属主体优先于仅缺融资、估值的主体，同组按最近关联新闻时间排序。刚取得资料链接的主体优先。旧 knownLinkResearchState 一次性同步到独立账本，缺少日期或页面明细的旧记录保守预留额度，并报告 unknownDateReservations。

私有账本位于 work/company-research-budget：ledger.json 保存请求前占位，results 保存成功建议及原 checkedAt，model-cache 保存原版本缓存与失败占位。账本独立于候选发布和单次 run 目录；后续失败、另起本地运行不能清掉旧请求记录或重置小样本额度。同输入成功结果回放不再读网页或调用模型，不把资料日期改成恢复日期。账本损坏、锁冲突、批次跨北京时间日期时关闭新请求，主新闻流程继续。

GitHub 使用单独的每日研究租约绑定 run/attempt，先保存并读回再开放新请求；默认小样本仍守住 5/10/5，全量模式解除此数量上限但保留同日运行归属与恢复保护。Actions cache 仅保存不含正文的 lease.json，私有账本和模型结果仅进入加密恢复包。缓存未命中时检查保留的工作流历史；已有当日或仍活跃的跨日运行、重跑、历史不完整或 API 不可用时保守延后，不能以缓存消失证明未花费。早先只跑 dry-run 的记录也可能保守占用当天机会。

该保护以同仓库串行执行及 GitHub 运行历史保留为前提，不是跨本地电脑、其他仓库的账户总费用硬限；管理员删除缓存与历史也会破坏判断依据。失败后的成功建议通过[加密恢复入口](PIPELINE_RECOVERY.md)回放，不依赖重新购买一次补全。平台依据见 [Actions 缓存说明](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching) 和 [运行历史 API](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)。

新记录保存主体、链接、缺失/补入字段、页面读取结果及安全错误类型。completed_no_supported_fields 表示模型完成但没有合格增量；no_readable_page 表示没有取得可用正文；model_or_evidence_failed 表示模型或证据处理失败。旧 completed 记录缺少逐字段结果时不能当成资料已完整核实。queue 和 notAttempted 明确记录余项及未启动原因，整体新闻流程不因可选资料补全熔断而失败。

历史 Manus 寻链配额缓存及旧任务记录保留，不删除以重置尝试；当前服务已停用，不创建新任务。已知网页补全独立处理，停用寻链不影响主新闻流程。

## 证据与入库

当前只读取审核资料链接及已有新闻页；历史 Manus 返回的 URL 仍只是线索。DeepSeek 使用实际网页正文，模型回答不能直接充当联网事实。HTTPS 页面读取拒绝跨域跳转，空正文和风险页面不进入模型。

自动建议逐字核对引文，并检查注册时间、累计融资／估值和团队口径。通过建议只补空白，标记 verificationStatus=provisional、来源与原因，不覆盖已有值。待归属产品只记录 candidateOwners，不自动改名或合并。没有支持证据继续留空；不得引入新闻未提及的新产品。

单轮融资及市值不能经网页补全重新写入累计融资或融资估值，检查建议值与来源引文两处含义。服务器、数据存储和跨境传输地点不能单独证明公司国家。

成立时间优先法人登记，用 dateBasis=registration 与 legalEntity 说明法人范围；阿拉伯数字日期保留原精度。国家用 countryBasis 区分总部、注册地、公司地址或隐私政策定义。经审阅的 replace=true 规则可更新既有标量并保留旧证据，暂定建议不能借此覆盖。

资料更新时间与新闻时间分开：当前由用户手动启动完整流程，主新闻默认冻结启动时刻的北京时间最近 24 小时；09:30 固定窗口只用于显式历史复核。公司背景页面不受新闻 24 小时限制，账本仍按实际执行日记录。补全完成后随候选发布，不改新闻原日期和排序。

## 验收与历史

离线回归使用 python scripts/test_pipeline.py offline，不调用付费 API。当前直采全量已获授权；默认小样本及旧 `research.propose(full_review=True)` 人工研究的历史记录不因此被改写，费用台账和恢复语义仍保留。每次人工资料修改仍经候选审核与发布入口。

旧 company-enrichment.html 已退役，不能作为当前补全页面入口。保留的 company-profile-review.json 定向记录与本批公司 knownLinkResearch 记录分开，不把独立补全冒称完整采集批次；历史审计见 [2026-09-20 公司资料与单源验证](../history/2026-09-20-COMPANY_PROFILE_AND_CANARY.md)。每次手动运行仍需核对来源、窗口、资料增量、费用和部署状态。

GLM-4V／Baichuan-M3 原生搜索试验保持停用，不重复失败查询。历史测试及旧未接入状态见[整理前操作记录](../history/2026-09-15/maintenance-before-organization/COMPANY_WEB_RESEARCH.md)；一次性全库结果见[全库复核记录](../history/2026-09-15/COMPANY_FULL_RESEARCH.md)。
