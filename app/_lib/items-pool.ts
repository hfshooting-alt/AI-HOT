// 上游列表的公共分页逻辑。空页也算成功；后续页失败保留已获取的数据。
import type { ItemsPage, NewsItem } from "./types";
import type { UpstreamResult } from "./upstream";

export async function fetchItemsPool(fetchJSON: (path: string) => Promise<UpstreamResult>) {
  const items: NewsItem[] = [];
  let cursor: string | undefined;
  let live = false;
  for (let i = 0; i < 3; i++) {
    const params = new URLSearchParams({ limit: "50" });
    if (cursor) params.set("cursor", cursor);
    const res = await fetchJSON(`/api/public/items?${params}`);
    if (!res.ok) break;
    live = true;
    const page = res.data as ItemsPage;
    items.push(...(page.items || []));
    if (!page.hasNext || !page.nextCursor) break;
    cursor = page.nextCursor;
  }
  return { items, live };
}
