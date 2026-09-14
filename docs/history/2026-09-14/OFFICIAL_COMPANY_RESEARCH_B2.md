# 官网资料补全第二批

助手检索官方页面，DeepSeek-V4-Pro依据摘录提出字段建议，再人工复核。3次调用、1523 tokens，无Manus调用、无失败重试。

| 主体 | 已补字段 | 官方依据 |
|---|---|---|
| Replit | 美国；2016年成立 | https://replit.com/news/replit-opens-london-office |
| 特斯拉 | 美国 | https://ir.tesla.com/press-release/tesla-releases-results-2024-annual-meeting-stockholders |
| Swissport | 瑞士 | https://www.swissport.com/en/news/current-news/2023/finacity-facilitates-a-75-million-receivables-securitization-program-for-swissport-international |

Replit与Swissport按官网明确总部国家；Tesla按明确注册州，2024年的迁册时间没有当作成立时间。Swissport证据来自2023年公告，后续发现变更需更新。Cursor和Tailscale涉及品牌/法人范围，暂保留原值。

审核包：395b884cfaf941699be217e4e897a2b8。65主体、83关联产品、8待核实，缺国家34。候选通过正式发布门禁，逐项断言新闻快照、原报道日期、产品名、产品关系、来源文章和待核实/排除记录不变。仅更新资料时间及字段证据。

原始摘录、模型响应与应用脚本在本地work/official-research-20260914-b2。此次仍为人工监督的联网核验，未接每日自动检索。
