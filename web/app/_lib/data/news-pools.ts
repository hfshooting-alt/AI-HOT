import type { NewsItem, NewsPoolMode, Snapshot } from "../domain/types";

function requestedPool(snap: Snapshot, mode: NewsPoolMode) {
  return mode === "selected" ? snap.garenaSelected : snap.all;
}

/** Missing or malformed data is distinct from an intentionally empty batch. */
export function newsPoolError(snap: Snapshot | null, mode: NewsPoolMode = "all"): string | null {
  if (!snap) return "本轮新闻数据暂不可用，请稍后刷新。";
  const pool = requestedPool(snap, mode);
  if (!Array.isArray(pool?.items)) return "本轮文章数据不完整，等待重新发布。";
  if (pool.items.some(item => !item || typeof item !== "object"
      || typeof item.id !== "string" || typeof item.title !== "string")) {
    return "本轮文章数据格式异常，等待重新发布。";
  }
  return null;
}

/** Read only the published pool and retain each collector's own identity. */
export function poolFromSnapshot(snap: Snapshot, mode: NewsPoolMode = "all"): NewsItem[] {
  if (newsPoolError(snap, mode)) return [];
  return requestedPool(snap, mode)!.items.filter(item =>
    (item.id.startsWith("manus:") && item.id.length > 6
      && (item.collector === undefined || item.collector === "manus"))
    || (item.id.startsWith("direct:") && item.id.length > 7 && item.collector === "direct_site"))
    .sort((a, b) => (Date.parse(b.publishedAt || "") || 0) - (Date.parse(a.publishedAt || "") || 0));
}
