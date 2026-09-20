# 公司资料联网补全

当前每日流程：新闻关联主体 → 可选 Manus 资料链接发现 → 读取原页 → DeepSeek 提议 → 引文与字段口径校验 → 暂定空白字段／候选归属 → 候选校验及统一发布。

## 入口与模块

统一入口 scripts/run_pipeline.py 在 overview 阶段传入 --known-link-research；full 模式同时传入 --discover-company。aihot-only 不执行 Manus 链接发现。单独运行公司构建时，只有显式开启这些参数才调用资料补全。--no-promote 仅阻止发布，不能阻止付费。

[公司模块导航](../../scripts/company_index/README.md) 说明各处理职责。审阅规则保存在 config/company_research.json；补全记录和候选归属随公司 JSON 发布，完整响应与台账留在忽略目录 work/。

## 每日边界

| 步骤 | 范围与上限 | 失败处理 |
| --- | --- | --- |
| Manus 链接发现 | 每天最多 1 个缺资料公司或待归属产品；Lite；提示词要求最多 3 次搜索、3 页；300 秒观察；20 credits 观察止损 | 创建不重试，回收已返回链接；停止无法确认时保护性暂停后续搜索 |
| 原页读取 | 北京时间实际执行日最多 5 个主体、10 个页面；每主体最多 2 个链接，读取前持久预留 | 单页失败隔离，同主体其他页继续；失败预留不退回 |
| DeepSeek 补全 | 同一实际执行日最多 5 次请求，请求前持久预留，仅补缺失字段 | 成功结果保存后可离线回放；超时、失败和状态不明不自动重试 |

公司搜索与新闻媒体采集费用分开。20 credits 是观察止损线，不能保证服务端不超额。历史已尝试主体不自动重新搜索；已知链接按主体、模型、链接及最新报道去重，同输入成功／失败均跳过，新报道可再次触发。没有新报道时不会主动巡检官网变化。未检查主体保留到后续机会，不保证当日清空全库。

基本资料（主营业务、国家、法人注册日期、团队）与待归属主体优先于仅缺融资、估值的主体，同组按最近关联新闻时间排序。刚取得资料链接的主体优先。旧 knownLinkResearchState 一次性同步到独立账本，缺少日期或页面明细的旧记录保守预留额度，并报告 unknownDateReservations。

私有账本位于 work/company-research-budget：ledger.json 保存请求前占位，results 保存成功建议及原 checkedAt，model-cache 保存原版本缓存与失败占位。账本独立于候选发布和单次 run 目录；后续失败、另起本地运行不能重置当天额度。同输入成功结果回放不再读网页或调用模型，不把资料日期改成恢复日期。账本损坏、锁冲突、跨北京时间日期时关闭新请求，主新闻流程继续。

GitHub 使用单独的每日研究租约：同仓库串行工作流只有一个 run/attempt 可占用当天 5/10/5 额度；先保存并读回租约，再开放付费。Actions cache 仅保存不含正文的 lease.json，私有账本和模型结果仅进入加密恢复包。缓存未命中时还检查保留的工作流历史；已有当日或仍活跃的跨日运行、重跑、历史不完整或 API 不可用均跳过新研究，不以缓存消失视为额度重置。早先只跑 dry-run 的记录也可能保守占用当天机会。

该保护以同仓库串行执行及 GitHub 运行历史保留为前提，不是跨本地电脑、其他仓库的账户总费用硬限；管理员删除缓存与历史也会破坏判断依据。失败后的成功建议通过[加密恢复入口](PIPELINE_RECOVERY.md)回放，不依赖重新购买一次补全。平台依据见 [Actions 缓存说明](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching) 和 [运行历史 API](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)。

新记录保存主体、链接、缺失/补入字段、页面读取结果及安全错误类型。completed_no_supported_fields 表示模型完成但没有合格增量；no_readable_page 表示没有取得可用正文；model_or_evidence_failed 表示模型或证据处理失败。旧 completed 记录缺少逐字段结果时不能当成资料已完整核实。queue 和 notAttempted 明确记录余项及未启动原因，整体新闻流程不因可选资料补全熔断而失败。

GitHub 在创建任务前按北京时间日期恢复配额缓存，预留运行所有者并保存、读回确认。缓存不可用时跳过公司搜索；同日另一轮或重跑不再次创建。不要删除配额缓存绕过保护。搜索阶段跳过不影响已知链接补全及主新闻流程。

## 证据与入库

Manus 返回 URL 线索，DeepSeek 使用实际网页正文；模型搜索回答不能直接充当事实。HTTPS 页面读取拒绝跨域跳转，空正文和风险页面不进入模型。

自动建议逐字核对引文，并检查注册时间、累计融资／估值和团队口径。通过建议只补空白，标记 verificationStatus=provisional、来源与原因，不覆盖已有值。待归属产品只记录 candidateOwners，不自动改名或合并。没有支持证据继续留空；不得引入新闻未提及的新产品。

单轮融资及市值不能经网页补全重新写入累计融资或融资估值，检查建议值与来源引文两处含义。服务器、数据存储和跨境传输地点不能单独证明公司国家。

成立时间优先法人登记，用 dateBasis=registration 与 legalEntity 说明法人范围；阿拉伯数字日期保留原精度。国家用 countryBasis 区分总部、注册地、公司地址或隐私政策定义。经审阅的 replace=true 规则可更新既有标量并保留旧证据，暂定建议不能借此覆盖。

资料更新时间与新闻时间分开：每日北京时间 09:30 启动，主新闻窗口固定前日 09:30 至当日 09:30；公司背景搜索不受 24 小时限制。补全完成后才随批次发布，不改新闻原日期和排序。

## 验收与历史

离线回归使用 python scripts/test_pipeline.py offline，不调用付费 API。真实全库研究必须明确授权，research.propose(full_review=True) 的一次性额度不改变每日限制。每次人工资料修改仍经候选审核与发布入口。

公开 company-enrichment.html 展示当前字段空缺、最近定向补全及已发布批次的自动记录。定向补全记录位于 company-profile-review.json，明确独立于每日运行；历史审计见 [2026-09-20 公司资料与单源验证](../history/2026-09-20-COMPANY_PROFILE_AND_CANARY.md)。下一次真实定时任务仍需核对来源、窗口、资料增量、费用和部署状态。

GLM-4V／Baichuan-M3 原生搜索试验保持停用，不重复失败查询。历史测试及旧未接入状态见[整理前操作记录](../history/2026-09-15/maintenance-before-organization/COMPANY_WEB_RESEARCH.md)；一次性全库结果见[全库复核记录](../history/2026-09-15/COMPANY_FULL_RESEARCH.md)。
