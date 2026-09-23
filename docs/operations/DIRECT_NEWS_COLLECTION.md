# 媒体页面直采

2026-09-23 用户批准将直采试点推进到完整候选。现有20来源配置与收录、筛选规则保持；新增 `direct-only` 模式使用匿名HTTP获取列表和详情，模型只做正文加工。AIHOT仍停用，定时仍关闭。Manus模式保留为显式可选路线，本模式不会创建Manus任务，包括可选公司链接发现。

```powershell
python scripts/run_pipeline.py run --source-mode direct-only --skip-search --no-promote
python scripts/run_pipeline.py review-candidate --candidate work/runs/<日期>/ten-am/<运行ID>/workspace
python scripts/run_pipeline.py publish-candidate --candidate work/reviewed-candidates/<审核ID>
```

首次运行冻结北京时间最近24小时，所有采集和后续阶段共用 `NEWS_COLLECTION_END`。列表时间只帮助找候选，逐篇验证配置账号、标题及详情原始发布时间；修改时间、评论、点赞和URL日期不能用于入窗。既有“昨天”自然日例外不改变。没有正文但元数据合格的文章保留“待正文”；正文合格者全部摘要分类，实质AI相关性单独决定精选，只有精选供公司/产品/融资抽取。

来源最多并发3；每来源最多10页、200详情、240次匿名HTTP，无自动失败重试，单响应3MB、20秒。腾讯根据实测 `offsetInfo` 原样传递到下一页的 `offset_info`；网易只用已观察的账号SSR列表，不能凭空构造翻页API。白鲸按首页脚本的POST分页；Elsewhere仅既定作者，不把混合站点的其他作者当成本信源；机器之心返回数据服务广告页时明确失败。

观察到列表跨过下界不等于证明媒体没有漏发或转载延迟。状态分可访问、窗口内已核实样本、已遍历列表范围；范围不完整仍可发布核实文章，不能称20源全天无遗漏。详情失败逐条记录，已核实条目保留。

私有HTTP收据、原始页面和逐源诊断放在候选 `inputs/direct/`。公开文章使用 `collector=direct_site`、`direct:` ID；schema3 feed保留在兼容路径 `data/manus/current.json`，名称不表示经过Manus。schema1/2仍严格只接受Manus。原始正文不进入公开JSON，公司和融资正文依据本批精选的ID+URL绑定，禁止错用同名旧正文。

付费调用上界按实际合格正文数计算：每篇一次相关性、一次摘要分类，精选每篇最多一次公司抽取，精选融资每篇最多一次融资抽取；复用匹配提示词/模型/内容版本的成功缓存。公司官网补空沿既有日租约，最多5主体/10页/5次模型，不恢复失败模型原生搜索。请求异常保存候选与已完成缓存；不靠扩大预算或改写旧状态制造成功。

全部阶段完成后，先离线回归与逐项内容审核，再用 reviewed-candidate 校验并晋升。Git提交及Pages部署后核对线上三份JSON与提交文件SHA256，才报告已上线。

本次整批结果与未完成覆盖见[2026-09-23验收记录](../history/2026-09-23-DIRECT_NEWS_ACCEPTANCE.md)。修正导入始终保留原采集和原模型响应，明确区分旧版本成功结果、新正文请求及离线审校，不改写旧运行指纹。
