任务：从以下唯一配置入口采集文章标题、链接和原始发布时间。立即打开入口，不复述计划、不创建文件、不提取正文或摘要、不搜索替代来源。

{{SOURCES}}

固定北京时间窗口：{{WINDOW_START}}（含）至{{WINDOW_END}}（不含）。target_date仅为批次标识，不要求发布日期等于它，也不随实际开工时间移动窗口。

执行顺序：
1. 核对列表名称为配置媒体或明确配置的显示名，不猜别名。机器之心产业页只收详情署名机器之心的文章，author必须写机器之心，不能为null；站点标志或列表署名不能代替详情署名。排除ScienceAI、新闻资讯及其他机构。详情正文或署名未核实不得发complete文章。腾讯用图文，网易用全部。列表等待累计最多30秒，必要时切换标签一次、原URL重开一次；仍失败就结束并报告list_not_loaded或identity_mismatch，不循环刷新。
2. 从顶部按时间顺序处理。列表明确晚于窗口的先跳过；候选打开详情核验标题、署名、正文存在性及发布时间，可读取同文datePublished/time标签。原始发送时间有效；评论、点赞、互动、编辑时间和dateModified无效；URL日期不能作时间证据。中国媒体无时区时间按Asia/Shanghai，明确时区换算北京时间。
3. 每核实一篇立即单独发进度消息：AIHOT_ARTICLE {完整文章JSON}。然后继续下一篇，不等待全页扫描完成。文章字段：account_name、source_platform、source_home_url逐字复制配置；article_url、title必填；published_at为含时区ISO8601，published_date为北京日期；published_time_text无相对文字时null；author无署名时null；extraction_status="complete"；note写明身份和时间证据所在页。
4. 时间例外：原文或对应列表卡片写“昨天”，前一自然日全天纳入；“N小时前/分钟前”逐字记published_time_text，published_at/published_date可null交本地换算，不编造精确时间。只有日期且处于窗口两天内的隔离；相对时间边界不确定也隔离。单篇失败继续，并记录覆盖缺口。
5. 遇到早于start的非置顶文章可结束；只有日期但早于开始日亦可作为边界。置顶、“昨天”不能充当09:30边界。未确认起点边界或完整列表末尾须继续翻页；无法继续则保留已回传文章并标partial，不把加载失败当成空列表。

最终仅输出JSON（不加围栏），根字段source_group、target_date、source_audits、articles。articles为已核实记录。source_audits中每个配置账号恰好一次，字段account_name、source_status、article_count、note。完整覆盖且无遗漏才complete（可以0篇）；有文章但覆盖未确认或存在隔离则partial；无文章且访问/核验失败则failed。计数等于最终文章数，partial/failed的note以boundary_unverified、detail_time_unavailable、list_not_loaded或identity_mismatch开头，注明实际核实到哪里。不得编造完整覆盖。
