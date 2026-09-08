// 热点榜代理：GET /api/hot -> aihot /api/v1/hot-topics（60s 缓存）
import { NextResponse } from "next/server";
import { upstreamJSON } from "../../_lib/data/upstream";

export async function GET() {
  const res = await upstreamJSON("/api/v1/hot-topics");
  if (!res.ok) {
    return NextResponse.json(
      { error: `热点榜上游不可用（${res.status}）` },
      { status: res.status >= 500 ? 502 : res.status },
    );
  }
  return NextResponse.json(res.data, {
    headers: { "Cache-Control": "s-maxage=60, stale-while-revalidate=300" },
  });
}
