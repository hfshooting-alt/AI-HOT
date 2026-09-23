# 媒体页面直采

2026-09-23 用户确认暂时完全停用Manus，默认 `direct-only`，`full` 同样指向直采。现有20来源配置与收录、筛选规则保持；匿名HTTP获取列表和详情，模型统一使用并行科技DeepSeek-V4-Pro。AIHOT仍停用，GitHub恢复北京时间每天09:30调度（UTC `30 1 * * *`），手动入口保留；未恢复Codex定时跟进。`config/services.json` 在真实HTTP前关闭Manus和Tavily，覆盖旧新闻发现、公司链接发现及Manus探针，旧代码/证据保留供追溯。

```powershell
python scripts/run_pipeline.py run --no-promote
python scripts/run_pipeline.py review-candidate --candidate work/runs/<日期>/ten-am/<运行ID>/workspace
python scripts/run_pipeline.py publish-candidate --candidate work/reviewed-candidates/<审核ID>
```

GitHub 定时使用 UTC cron `30 1 * * *`（北京时间每天 09:30）。核对本次 run 的审计状态、event、run ID、attempt 与 head SHA 后，以 `created_at` 转北京时间最近已到达的 09:30 冻结截止时刻：09:30 前创建取前一天 09:30，之后取当天 09:30；窗口为此前 24 小时 `[start, end)`。`NEWS_COLLECTION_END` 贯穿各阶段，排队跨午夜或重跑不滑窗；创建时间无法可靠取得时，在采集与模型付费前停止。手动运行仍在启动时冻结 `rolling-24h`，可用含时区的 `--window-end` 显式指定；恢复沿原窗口。 列表时间只帮助找候选，逐篇验证配置账号、标题及详情原始发布时间；修改时间、评论、点赞和URL日期不能用于入窗。既有“昨天”自然日例外不改变。没有正文但元数据合格的文章保留“待正文”；正文合格者全部摘要分类，实质AI相关性单独决定精选，只有精选供公司/产品/融资抽取。

来源最多并发3；每来源最多10页、200详情、240次匿名HTTP，无自动失败重试，单响应3MB、20秒。腾讯根据实测 `offsetInfo` 原样传递到下一页的 `offset_info`；网易只用已观察的账号SSR列表，不能凭空构造翻页API。白鲸按首页脚本的POST分页；Elsewhere仅既定作者，不把混合站点的其他作者当成本信源；机器之心返回数据服务广告页时明确失败。

观察到列表跨过下界不等于证明媒体没有漏发或转载延迟。状态分可访问、窗口内已核实样本、已遍历列表范围；范围不完整仍可发布核实文章，不能称20源全天无遗漏。详情失败逐条记录，已核实条目保留。

2026-09-23可靠性补充：逐源 `health` 区分来源失败、部分列表/详情失败、待正文、有核实文章、已遍历列表内无窗口文章、覆盖未完成且无核实样本。记录失败原因计数、正文缺口及最新已核实发布时间；GitHub运行摘要显示对应诊断表。该表仅说明采集阶段，模型加工与发布仍看各自阶段及发布回执，不把无样本解释为原公众号没更新。

单篇补抓使用独立入口（无需模型或Manus，不自动发布）：

```powershell
$env:PYTHONPATH='scripts'
python -m direct_source.recovery --collection work/<原批次>/collection.json --account "智东西" --url "<原批次记录的失败或缺正文URL>" --out-dir work/<新的独立恢复目录>
```

一次选定一个来源、1至20条URL，只请求原批次确实尝试过且失败或缺正文的详情；其余列表/正文从原HTTP收据和哈希校验后的页面回放。原窗口和其他来源不变，原始文件、成功文章不覆盖，禁止把恢复目录放进原证据目录。403/401/429不在此入口重试；原始列表缺失、哈希不一致或新版适配器需要未保存的请求时不扩大发现范围。旧收据未保存编码时只按UTF-8回放，解码导致身份/标题不匹配仍隔离。

结果写新 `collection.json`、`recovery-plan.json` 和 `attempt-result.json`，保留原集合路径/哈希、请求数与未恢复项。原覆盖结论保持保守；补抓不能证明重新遍历整个24小时。对已有元数据，标题或发布时间变化不覆盖原条目。该工具不重写旧state/fingerprint，也不自动续跑；后续模型处理须在新候选中显式使用恢复集合，并经现有reviewed-candidate审核晋升。暂不自动跨批次复用正文，避免过期正文和日期证据混入新窗口。

私有HTTP收据、原始页面和逐源诊断放在候选 `inputs/direct/`。公开文章使用 `collector=direct_site`、`direct:` ID；schema3 feed保留在兼容路径 `data/manus/current.json`，名称不表示经过Manus。schema1/2仍严格只接受Manus。原始正文不进入公开JSON，公司和融资正文依据本批精选的ID+URL绑定，禁止错用同名旧正文。

付费调用按实际合格正文数计算：每篇一次相关性、一次摘要分类，精选每篇最多一次公司抽取，精选融资每篇最多一次融资抽取；复用匹配提示词/模型/内容版本的成功缓存。直采公司资料默认显式 `--research-full-review`：按有限待补全队列执行，每主体最多2个已知网页、每输入最多1次新模型请求，无5主体日额度限制；请求前持久占位，旧额度和结果不清零。默认小样本/历史恢复仍保留原租约语义；全量模式不启动Manus发现，不恢复失败模型原生搜索。新资料必须有实际读取的网页及逐字证据；无可用URL不等于已全面搜索。请求异常保存候选与已完成缓存，不改写旧状态。

本地 `.env` 支持 `PARATERA_API_KEY`，旧 `DEEPSEEK_API_KEY` 可继续承载同一并行科技密钥；前者只在并行科技域名使用并优先选择。GitHub定时及手动工作流仅使用仓库Secret `PARATERA_API_KEY`，固定并行科技地址及DeepSeek-V4-Pro，不回退另一提供商。网页抓取无需模型搜索工具或Manus密钥。前端设置页已删除，配置通过 `.env` / Secrets 管理；独立后台设置服务和CLI仅保留兼容。

全部阶段完成后，先离线回归与逐项内容审核，再用 reviewed-candidate 校验并晋升。Git提交及Pages部署后核对线上三份JSON与提交文件SHA256，才报告已上线。

新定时仍须按[真实验收清单](NEXT_SCHEDULED_ACCEPTANCE.md)核对触发、冻结窗口、逐源覆盖、用量与Pages；配置正确不等于准点或全覆盖。本次整批结果与未完成覆盖见[2026-09-23验收记录](../history/2026-09-23-DIRECT_NEWS_ACCEPTANCE.md)。修正导入始终保留原采集和原模型响应，明确区分旧版本成功结果、新正文请求及离线审校，不改写旧运行指纹。
