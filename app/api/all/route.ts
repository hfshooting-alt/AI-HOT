// 全部 AI 动态聚合：GET /api/all
// 聚合 /api/public/items 前 3 页全量条目，归一化分类并统计标签，供前端标签筛选
import { NextResponse } from "next/server";
import { fetchItemsPool } from "../../_lib/items-pool";
import { newestFirst, normalizeUpstreamItem } from "../../_lib/news-normalization";
import { upstreamJSON } from "../../_lib/upstream";

export async function GET() {
  const { items: pool, live } = await fetchItemsPool(upstreamJSON);
  const items = pool.map(normalizeUpstreamItem).sort(newestFirst);

  const counter = new Map<string, number>();
  for (const it of items) counter.set(it.category || "行业动态", (counter.get(it.category || "行业动态") || 0) + 1);
  const tags = [...counter.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count);

  return NextResponse.json(
    { items, tags, live },
    { headers: { "Cache-Control": "s-maxage=60, stale-while-revalidate=300" } },
  );
}
