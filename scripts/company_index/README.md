# 公司与产品库代码导航

从仓库根执行 scripts/build_company_overview.py；本目录按处理职责拆分。命令参数、公开 JSON 和历史缓存位置保持稳定。

| 职责 | 文件 |
| --- | --- |
| 字段、模型版本、预算与北京时间 | config.py |
| 新闻输入、实体抽取与增量合并 | inputs.py、extraction.py、entities.py |
| 产品关系和排除规则 | products.py |
| 人工规则、暂定字段、主体归属 | identity.py |
| 每日联网补全编排和报告 | daily_research.py |
| 网页读取、字段证据门禁 | page_evidence.py |
| DeepSeek 提议、逐字核验、请求缓存和台账 | research.py |
| Manus 链接发现、每日配额、停止和回收 | discovery.py |
| 历史模型原生搜索试验（生产停用） | search.py |
| 输出和原子写入 | output.py |

daily_research 保留 read_page、eligible_fact 导入入口，实现集中在 page_evidence。python -m company_index.discovery --reserve 仍是工作流配额预留入口，需设置 PYTHONPATH=scripts。

排错顺序：先查 companyDiscovery 的链接发现状态，再查 knownLinkResearch 的页面／模型／隔离记录，最后对照私有台账和字段来源。不要用重新付费运行代替读取已有证据。

业务边界见[操作说明](../../docs/operations/COMPANY_WEB_RESEARCH.md)。
