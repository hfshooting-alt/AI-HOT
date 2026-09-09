// 精选流聚合：GET /api/featured?category=&q=
// 聚合 /api/v1/items 前 3 页，仅保留 selected 精选，归一化分类后按分类/关键词过滤
import { NextResponse } from "next/server";
import { fetchItemsPool } from "../../_lib/data/items-pool";
import { newestFirst, normalizeUpstreamItem } from "../../_lib/data/news-normalization";
import type { NewsItem } from "../../_lib/domain/types";
import { upstreamJSON } from "../../_lib/data/upstream";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const category = url.searchParams.get("category") || "";
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();

  const { items: pool, live } = await fetchItemsPool(upstreamJSON);
  if (!live) {
    return NextResponse.json({ items: [], live: false }, { status: 200 });
  }

  let items: NewsItem[] = pool.filter((it) => it.selected === true).map(normalizeUpstreamItem);
  if (category) items = items.filter((it) => it.category === category);
  if (q) {
    items = items.filter(
      (it) =>
        (it.title || "").toLowerCase().includes(q) ||
        (it.summary || "").toLowerCase().includes(q),
    );
  }
  items.sort(newestFirst);

  return NextResponse.json(
    { items, live: true },
    { headers: { "Cache-Control": "s-maxage=60, stale-while-revalidate=300" } },
  );
}
