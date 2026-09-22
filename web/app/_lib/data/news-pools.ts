import type { NewsItem, NewsPoolMode, Snapshot } from "../domain/types";

function hasSelectedPool(snap: Snapshot): boolean {
  return Object.prototype.hasOwnProperty.call(snap, "garenaSelected");
}

function usesSeparatePools(snap: Snapshot | null): boolean {
  return Boolean(snap && (snap.newsSelectionVersion === 1 || hasSelectedPool(snap)));
}

function newestFirst(items: NewsItem[]): NewsItem[] {
  return [...items].sort((a, b) =>
    (Date.parse(b.publishedAt || "") || 0) - (Date.parse(a.publishedAt || "") || 0));
}

/** An explicit pool, including an empty one, is authoritative. */
export function poolFromSnapshot(snap: Snapshot, mode: NewsPoolMode = "all"): NewsItem[] {
  if (mode === "selected") {
    if (hasSelectedPool(snap)) return newestFirst(snap.garenaSelected?.items || []);
    // A malformed new snapshot must not promote its unfiltered articles.
    if (snap.newsSelectionVersion === 1) return [];
  }
  // Legacy all already contained the site's screened articles.
  if (Array.isArray(snap.all?.items)) return newestFirst(snap.all.items);
  if (snap.publicationMode === "pipeline" || usesSeparatePools(snap)) return [];
  const seen = new Set<string>();
  const pool: NewsItem[] = [];
  for (const view of [snap.daily, snap.weekly]) {
    for (const section of view?.sections || []) {
      for (const item of section.items || []) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        pool.push(item);
      }
    }
  }
  return newestFirst(pool);
}

/** Live upstream data may only supplement the old, non-pipeline all view. */
export function shouldLoadLiveNews(snap: Snapshot | null, mode: NewsPoolMode): boolean {
  return mode === "all" && snap?.publicationMode !== "pipeline" && !usesSeparatePools(snap);
}

/** New snapshots already assign reviewed supplements to both authoritative pools. */
export function shouldMergeReviewedNews(snap: Snapshot | null): boolean {
  return !usesSeparatePools(snap);
}
