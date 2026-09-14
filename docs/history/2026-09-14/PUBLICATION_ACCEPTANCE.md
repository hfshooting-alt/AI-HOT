# 正式发布与云端验收

- 代码f916bc0：整理交接、归档旧报告和失效配置；增加信源reasonCode与候选审核发布入口。
- 数据b23a6f3：审核199篇新闻、64家公司、78项公司产品、17项待归属产品；2条相关性排除、1条证据不足隔离。
- 本地禁网重建无网络尝试；模型缓存全部复用。323项Python、35项Node通过，TypeScript通过，静态构建通过。Windows退出清理断言由既有构建包装器校验静态文件新鲜度后处理。
- [Pages部署](https://github.com/hfshooting-alt/AI-HOT/actions/runs/34822652981)成功，正式URL为https://hfshooting-alt.github.io/AI-HOT/；远端snapshot与company-overview已验证，浏览器确认199条新闻和费用原因展示。
- [云端隔离测试](https://github.com/hfshooting-alt/AI-HOT/actions/runs/34822717448)成功：source_mode=aihot-only、promote=false、skip_search=true、窗口结束日2026-09-14。新闻、快照、公司、融资步骤完成；摘要与公司各新增1条、各命中198条缓存。未启动Manus，未覆盖正式数据。该测试不证明20个Manus来源完整覆盖，也不证明跨日增量已通过；云端相关性调用总量未在此报告量化。
- 审核包work/reviewed-candidates/bbc3047028da49c98fd5ef1370a2369f保留本地来源与校验值，不提交私有输入。历史候选与原采集状态未伪造为新全量成功。

下一步：检查新一天09:30定时任务及既有公司增量合并。沿用已确认业务规则；任何修改信源、预算、收录范围或失败发布口径前，先向用户说明影响并确认。
