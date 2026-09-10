// 日报代理：缺省时先取索引实际日期，再访问日期端点，避免 latest URL 被外部缓存复用旧值。
import { NextResponse } from "next/server";
import { upstreamJSON } from "../../_lib/data/upstream";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const date = url.searchParams.get("date") || "";
  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: "date 需为 YYYY-MM-DD" }, { status: 400 });
  }
  let targetDate = date;
  if (!targetDate) {
    const index = await upstreamJSON("/api/v1/dailies?limit=1");
    if (!index.ok) {
      return NextResponse.json(
        { error: `日报索引上游不可用（${index.status}）` },
        { status: index.status >= 500 ? 502 : index.status },
      );
    }
    const items = (index.data as { items?: { date?: string }[] }).items || [];
    targetDate = items[0]?.date || "";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      return NextResponse.json({ error: "AIHOT 暂无可用日报" }, { status: 404 });
    }
  }
  const path = `/api/v1/dailies/${targetDate}`;
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
