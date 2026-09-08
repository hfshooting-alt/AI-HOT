import { normalizeCategory } from "./format";
import type { NewsItem } from "./types";

/** 仅用于上游原始条目；快照与已合并的数据使用各自的 ID 规则。 */
export function normalizeUpstreamItem(it: NewsItem): NewsItem {
  return {
    ...it,
    id: `aihot:${it.id}`,
    sourceType: String(it.source || "").startsWith("公众号：") ? "wechat" : "aihot",
    category: normalizeCategory(it.category),
  };
}

export function newestFirst(a: NewsItem, b: NewsItem): number {
  return new Date(b.publishedAt || 0).getTime() - new Date(a.publishedAt || 0).getTime();
}
