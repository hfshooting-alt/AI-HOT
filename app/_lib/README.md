# 数据与领域工具

- `data/api.ts`：浏览器读取本站 API、快照、周报和融资数据，并合并数据池。
- `data/upstream.ts`、`items-pool.ts`：服务端上游请求与公共分页；供 `app/api/` 使用。
- `data/news-normalization.ts`：上游条目 ID、来源、分类转换和排序。
- `domain/types.ts`：前后端交换的数据结构；`taxonomy.ts`、`fundingTaxonomy.ts`：展示枚举。
- `display/format.ts`、`source.ts`：日期、配色、来源与关键词匹配。

依赖方向为 `data → display/domain`、`display → domain`；`domain` 保持纯类型/常量，不依赖页面或请求。
