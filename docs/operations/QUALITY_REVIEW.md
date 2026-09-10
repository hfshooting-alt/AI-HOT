# 候选公司库与分类复核

`review_all_scanned.py` 的成功计数代表模型调用完成，不代表所有实体与分类正确。发布前需要抽查主体身份、公司别名、新闻事件与分类边界。

2026-09-10 本地候选复核：302 条主体合并四组别名、分离 17 条产品/模型/非公司记录后，公司表保留 281 条；修正六条发布预告、模板更新、测评入口或安全事件误分类。此计数不代表剩余公司字段已全部完成外部核验。

审阅决定保存于 `config/quality_review.json`。分类记录包含新闻链接、理由以及标题和摘要哈希，正文展示内容改变后原决定失效，写入 `staleDecisions` 待重新检查。公司别名仅合并明确同一主体，不按母子公司关系自动合并；冲突字段和原始记录保存在 `reviewMergedRecords`。产品归属未确认时放入 `pendingEntities`，来源文章完整保留。

在仓库根目录对模型候选结果执行，无网络、无费用：

```powershell
python scripts/apply_quality_review.py --input work/review-20260910/full-review --output work/review-20260910/quality-review
```

输出公司库、快照及 `quality-audit.json`。输入目录保持不动；公司审阅规则已接入 build_company_overview，分类审阅规则已接入 build_snapshot；此命令仍可用于隔离复核。使用输出数据更新预览后，再检查表格排序、报道链接与分类。本地候选数据仍未晋升正式公开数据。

2026-09-10 后续：依据本地已采集报道中的明确表述，将 ChatGPT/Claude/Gemini 归入 OpenAI/Anthropic/Google；证据标为 article，不冒充官网核验。候选公司仍为281条，待核实主体由17减为14条。
