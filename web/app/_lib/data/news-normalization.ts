import { normalizeCategory } from "../display/format";
import type { AIHotV1Item, NewsItem } from "../domain/types";

/** 仅用于上游原始条目；快照与已合并的数据使用各自的 ID 规则。 */
export function normalizeUpstreamItem(it: AIHotV1Item | NewsItem): NewsItem {
  const source = typeof it.source === "string" ? it.source : it.source?.name || "AIHOT";
  const links = "links" in it ? it.links : undefined;
  const publishedAt = it.publishedAt || ("discoveredAt" in it ? it.discoveredAt : undefined);
  return {
    id: `aihot:${it.id}`,
    title: it.title,
    summary: it.summary || undefined,
    source,
    sourceType: source.startsWith("公众号：") ? "wechat" : "aihot",
    category: normalizeCategory(it.category || undefined),
    categoryUnclassified: !it.category,
    publishedAt,
    discoveredAt: "discoveredAt" in it ? it.discoveredAt : undefined,
    score: it.score,
    selected: it.selected,
    url: links?.original || ("url" in it ? it.url : undefined),
    permalink: links?.aihot || ("permalink" in it ? it.permalink : undefined),
    aihotUrl: links?.aihot || ("aihotUrl" in it ? it.aihotUrl : undefined),
    originalUrl: links?.original || ("originalUrl" in it ? it.originalUrl : undefined),
    reason: "reason" in it ? it.reason : undefined,
    timeBasis: it.publishedAt ? "published" : "discovered",
    classification: "classification" in it ? it.classification : undefined,
    mpName: "mpName" in it ? it.mpName : undefined,
  };
}

export function newestFirst(a: NewsItem, b: NewsItem): number {
  return new Date(b.publishedAt || 0).getTime() - new Date(a.publishedAt || 0).getTime();
}
