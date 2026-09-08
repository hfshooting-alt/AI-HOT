// 日报代理：GET /api/daily?date=YYYY-MM-DD -> aihot /api/v1/dailies/{date}（缺省 latest）
import { NextResponse } from "next/server";
import { upstreamJSON } from "../../_lib/data/upstream";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const date = url.searchParams.get("date") || "";
  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: "date 需为 YYYY-MM-DD" }, { status: 400 });
  }
  const path = date ? `/api/v1/dailies/${date}` : "/api/v1/dailies/latest";
  const res = await upstreamJSON(path);
  if (!res.ok) {
    return NextResponse.json(
      { error: `日报上游不可用（${res.status}）` },
      { status: res.status >= 500 ? 502 : res.status },
    );
  }
  return NextResponse.json(res.data, {
    headers: { "Cache-Control": "s-maxage=300, stale-while-revalidate=600" },
  });
}
