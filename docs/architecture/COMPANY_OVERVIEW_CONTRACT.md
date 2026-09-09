# 公司与产品 Overview 数据契约

生产者为 `scripts/build_company_overview.py`，正式数据写入 `data/company-overview/current.json`，网页副本为 `web/public/company-overview.json`，两者必须完全一致。

## 范围

输入覆盖快照 daily/weekly 与最新 Manus feed 的全部新闻类别。按 URL 去重；能匹配运行时正文时使用正文，否则使用标题和摘要。历史 `current.json` 作为增量基线，因此公司不会因为当天没有新报道而消失。

## 公司记录

每条公司记录包含稳定 `company:` ID、公司名、明确别名、产品名称、成立时间、国家、团队、业务、投资人、累计融资、估值、行业/地区维度、首次和最近出现时间。

`fieldSources` 为逐字段证据。每条证据必须包含字段值、文章 ID、原文 URL、标题、来源、发布时间和 `origin=article`。发生冲突时采用较新文章的值展示，同时保留所有历史证据；无来源的信息不得写入字段。

同一公司按规范化公司名和文章明确给出的别名合并。不会根据模型常识推断别名，也不会仅凭产品名猜测所属公司。

## 成本与失败

成功抽取按正文哈希、模型和 Prompt 版本缓存。`config/taxonomy.json → companyOverview` 控制单篇正文长度、并发、总时间和每轮新增文章调用上限。超过上限的文章记录为 deferred，后续运行继续处理。

输入非空但本轮没有任何文章成功抽取时拒绝发布，保留旧公司库。抽取成功但文章确实没有公司时允许空增量。正式输出不得包含正文或密钥。
