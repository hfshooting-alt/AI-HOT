// 客户端数据层：快照 + 本站 API 代理 + 降级策略
// 优先级：/snapshot.json（构建产物）→ /api/*（服务端代理 aihot API）→ 空态
import type {
  AllFeedResponse,
  CompanyOverview,
  DailyReport,
  FundingTable,
  HotTopicsResponse,
  ItemsPage,
  NewsItem,
  Snapshot,
  WeeklyJournal,
} from "../domain/types";

async function fetchJSON<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return (await r.json()) as T;
}

/** 构建时生成的快照数据（精选流 / 日报周报索引的数据源） */
export async function loadSnapshot(): Promise<Snapshot | null> {
  try {
    return await fetchJSON<Snapshot>("/snapshot.json");
  } catch {
    return null;
  }
}

/** 热点榜（代理 /api/v1/hot-topics，60s 服务端缓存） */
export async function loadHot(): Promise<HotTopicsResponse | null> {
  try {
    return await fetchJSON<HotTopicsResponse>("/api/hot");
  } catch {
    return null;
  }
}

/** 精选条目流（代理 /api/public/items，仅 selected，服务端过滤分类/关键词） */
export async function loadFeatured(category?: string | null, q?: string): Promise<NewsItem[]> {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (q) params.set("q", q);
  const data = await fetchJSON<{ items: NewsItem[]; live: boolean }>(`/api/featured?${params}`);
  return data.items || [];
}

/** 全部 AI 动态（聚合条目 + 分类标签统计） */
export async function loadAll(): Promise<AllFeedResponse | null> {
  try {
    return await fetchJSON<AllFeedResponse>("/api/all");
  } catch {
    return null;
  }
}

/** 官方历史日报完整内容（含版块与条目），失败返回 null */
export async function loadDailyReport(date: string): Promise<DailyReport | null> {
  try {
    const data = await fetchJSON<{ report?: DailyReport }>(`/api/daily?date=${encodeURIComponent(date)}`);
    return data.report ?? null;
  } catch {
    return null;
  }
}

/** 周报期刊数据（public/weekly/{weekStart}.json），classification 归一化为前端格式 */
export async function loadWeeklyJournal(weekStart: string): Promise<WeeklyJournal | null> {
  try {
    const data = await fetchJSON<WeeklyJournal>(`/weekly/${encodeURIComponent(weekStart)}.json`);
    data.items = (data.items || []).map((it) => {
      const raw = it.classification as { category?: string } | undefined;
      return raw?.category
        ? { ...it, classification: { ...it.classification, cat: raw.category } }
        : it;
    });
    return data;
  } catch {
    return null;
  }
}

/** 直连 items 分页（/api/items 代理透传 cursor） */
export async function fetchItemsPage(cursor?: string, limit = 50): Promise<ItemsPage | null> {
  try {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set("cursor", cursor);
    return await fetchJSON<ItemsPage>(`/api/items?${params}`);
  } catch {
    return null;
  }
}

/** 融资动态公司表格（构建时由 funding_table.py 离线生成）；模块级缓存跨视图复用，失败返回 null */
let fundingTableCache: FundingTable | null = null;
let fundingTableLoaded = false;

export async function loadFundingTable(): Promise<FundingTable | null> {
  if (fundingTableLoaded) return fundingTableCache;
  try {
    fundingTableCache = await fetchJSON<FundingTable>("/funding-table.json");
  } catch {
    fundingTableCache = null;
  }
  fundingTableLoaded = true;
  return fundingTableCache;
}

let companyOverviewCache: CompanyOverview | null = null;
let companyOverviewLoaded = false;

/** 全类别新闻沉淀的公司/产品数据库；构建产物不可用时返回 null。 */
export async function loadCompanyOverview(): Promise<CompanyOverview | null> {
  if (companyOverviewLoaded) return companyOverviewCache;
  try {
    companyOverviewCache = await fetchJSON<CompanyOverview>("/company-overview.json");
  } catch {
    companyOverviewCache = null;
  }
  companyOverviewLoaded = true;
  return companyOverviewCache;
}

/** 从快照 daily+weekly 合并出精选条目池（按 id 去重，publishedAt 降序） */
export function poolFromSnapshot(snap: Snapshot): NewsItem[] {
  const seen = new Set<string>();
  const pool: NewsItem[] = [];
  for (const view of [snap.daily, snap.weekly]) {
    for (const sec of view.sections || []) {
      for (const it of sec.items || []) {
        if (seen.has(it.id)) continue;
        seen.add(it.id);
        pool.push(it);
      }
    }
  }
  pool.sort((a, b) => new Date(b.publishedAt || 0).getTime() - new Date(a.publishedAt || 0).getTime());
  return pool;
}

/** 合并快照池与实时精选流：实时条目覆盖同 id 快照条目（保留快照的 LLM 分类标签），其余追加 */
export function mergePools(snapshotPool: NewsItem[], liveItems: NewsItem[]): NewsItem[] {
  const map = new Map<string, NewsItem>();
  for (const it of snapshotPool) map.set(it.id, it);
  for (const it of liveItems) {
    const key = it.id.startsWith("aihot:") ? it.id : `aihot:${it.id}`;
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
