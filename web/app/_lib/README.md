# 数据与领域工具

- `data/api.ts`：浏览器只读取已发布的快照、公司与融资数据，不请求外部新闻接口。
- `data/news-pools.ts`：独立读取 Manus 全部文章和 Garena投资精选，保留显式空集并识别坏数据；不回填历史或演示条目。
- `domain/types.ts`：前后端交换的数据结构；`taxonomy.ts`、`fundingTaxonomy.ts`：展示枚举。
- `display/format.ts`、`source.ts`：日期、配色、来源与关键词匹配。

依赖方向为 `data → display/domain`、`display → domain`；`domain` 保持纯类型/常量，不依赖页面或请求。
