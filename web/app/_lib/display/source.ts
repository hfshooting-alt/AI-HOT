// 新闻搜索匹配；保留文章来源文字、公众号名与原文链接检索。
export interface SearchableItem {
  title?: string;
  summary?: string;
  source?: string;
  mpName?: string | null;
  url?: string;
  permalink?: string;
}

/** 搜索匹配：标题 + 摘要 + 来源名 + 公众号名 + URL 小写包含匹配 */
export function matchItem(item: SearchableItem, kw: string): boolean {
  const query = kw.trim().toLowerCase();
  if (!query) return true;
  const hay = [
    item.title || "",
    item.summary || "",
    item.source || "",
    item.mpName || "",
    item.url || "",
    item.permalink || "",
  ]
    .join(" ")
    .toLowerCase();
  return hay.includes(query);
}
