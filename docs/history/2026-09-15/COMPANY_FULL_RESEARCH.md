# 当前公司库全量联网复核

用户授权一次性完成当前所有需要联网核验的记录。范围为65个原主体及8项待归属产品；不是重新采集新闻。原199条新闻、原文链接、文章发布时间及公司报道顺序保持。

## 结果与边界

- 73次DeepSeek-V4-Pro请求，报告139835 tokens，无Manus调用；共享台账最多73次，失败不自动付费重试。
- 初轮89个不同页面中72个可直接读取；对读取失败的主体使用搜索工具读取原页、监管文件补充证据。完整正文及模型响应仅留本地work/company-full-research，不公开。
- 人工复核后采用65条规则、142项字段或归属证据；原34个国家缺失降为11个。部分记录仍没有足够的同口径资料；每个字段均在公开核验报告中区分已核验、保留原报道值、未获合格证据。
- 当前64个主体、8个待归属产品。Cursor→Anysphere, Inc.；RunningHub→安徽海马云智能科技发展有限公司；Tripo→VAST。MSL作为Meta部门合并，保留新闻与原产品关系，部门名称不作为产品。
- 成立日期以法人登记为主，保留精度。MiniMax、WeRide显示上市控股法人名称；国家按总部所在地单列，不能把开曼控股主体等同于业务总部。Runway登记资料只确认2018年，不补月日。
- 单轮金额、未完成融资意向、捐赠不作累计股权融资。历史融资估值保留原时点，不称今日估值。公开资料不支持的当前团队信息不采纳。
- Grok Bot官网虽可读，页脚SpaceXAI LLC不足以确定与当前xAI档案的法律主体映射；仍待归属。Astra/Claw同名歧义，其他独立开发者产品也不强行归公司。

## 可见结果与溯源

company-research-review.html提供73条记录的搜索入口、逐字段状态、来源与说明；company-research-review.json保存本次检查快照。config/company_research.json保存审核规则，后续公司更新可重放；fieldSources保留旧证据，replace=true仅用于显式审核替换。日期证据包含dateBasis与legalEntity。

离线337项Python、37项Node及TypeScript检查通过。发布必须走review-candidate和publish-candidate，构建及Pages状态另行验证。此次研究不意味着每日自动搜索已接入；GLM-4V/Baichuan-M3失败路线保持暂停。
