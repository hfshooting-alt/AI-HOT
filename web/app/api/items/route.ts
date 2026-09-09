// items 分页透传代理：GET /api/items?limit=&cursor= -> AIHOT /api/v1/items
import { NextResponse } from "next/server";
import { upstreamJSON } from "../../_lib/data/upstream";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const params = new URLSearchParams();
  const limit = url.searchParams.get("limit");
  const cursor = url.searchParams.get("cursor");
  params.set("mode", "all");
  params.set("window", "7d");
  params.set("by", "timeline");
  params.set("limit", limit && /^\d+$/.test(limit) ? limit : "50");
  if (cursor) params.set("cursor", cursor);
  const res = await upstreamJSON(`/api/v1/items?${params}`);
  if (!res.ok) {
    return NextResponse.json(
      { error: `items 上游不可用（${res.status}）` },
      { status: res.status >= 500 ? 502 : res.status },
    );
  }
  return NextResponse.json(res.data, {
    headers: { "Cache-Control": "s-maxage=30, stale-while-revalidate=120" },
  });
}
