import type { NewsItem } from "../domain/types";

/** 合并快照池与实时全部动态：实时条目覆盖同 id 快照条目（保留快照的 LLM 分类标签），其余追加 */
export function mergePools(snapshotPool: NewsItem[], liveItems: NewsItem[]): NewsItem[] {
  const map = new Map<string, NewsItem>();
  for (const it of snapshotPool) map.set(it.id, it);
  for (const it of liveItems) {
    const key = /^(aihot|manus|wechat):/.test(it.id) ? it.id : `aihot:${it.id}`;
    const prev = map.get(key);
    map.set(
      key,
      prev
        ? { ...prev, ...it, id: key, classification: it.classification ?? prev.classification }
        : { ...it, id: key },
    );
  }
  const out = [...map.values()];
  out.sort((a, b) => new Date(b.publishedAt || 0).getTime() - new Date(a.publishedAt || 0).getTime());
  return out;
}
