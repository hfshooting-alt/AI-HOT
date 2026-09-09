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

/** 兼容站点根目录与 GitHub Pages 的 /AI-HOT/ 子路径。 */
function publicAsset(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  return `${base}${path.replace(/^\//, "")}`;
}

const STATIC_SITE = import.meta.env.VITE_STATIC_SITE === "true";

async function fetchJSON<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return (await r.json()) as T;
}

/** 构建时生成的快照数据（精选流 / 日报周报索引的数据源） */
export async function loadSnapshot(): Promise<Snapshot | null> {
  try {
    return await fetchJSON<Snapshot>(publicAsset("snapshot.json"));
  } catch {
    return null;
  }
}

/** 热点榜（代理 /api/v1/hot-topics，60s 服务端缓存） */
export async function loadHot(): Promise<HotTopicsResponse | null> {
  if (STATIC_SITE) {
    const snap = await loadSnapshot();
    return snap?.hot ? { schemaVersion: snap.hot.schemaVersion ?? 1, count: snap.hot.count ?? snap.hot.items.length, items: snap.hot.items } : null;
  }
  try {
    return await fetchJSON<HotTopicsResponse>(publicAsset("api/hot"));
  } catch {
    const snap = await loadSnapshot();
    return snap?.hot ? {
      schemaVersion: snap.hot.schemaVersion ?? 1,
      count: snap.hot.count ?? snap.hot.items.length,
      items: snap.hot.items,
    } : null;
  }
}

/** 精选条目流（代理 AIHOT /api/v1/items，仅 selected，服务端过滤分类/关键词） */
export async function loadFeatured(category?: string | null, q?: string): Promise<NewsItem[]> {
  if (STATIC_SITE) {
    const snap = await loadSnapshot();
    return snap?.featured || (snap ? poolFromSnapshot(snap) : []);
  }
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (q) params.set("q", q);
  try {
    const data = await fetchJSON<{ items: NewsItem[]; live: boolean }>(`${publicAsset("api/featured")}?${params}`);
    return data.items || [];
  } catch {
    const snap = await loadSnapshot();
    return snap?.featured || (snap ? poolFromSnapshot(snap) : []);
  }
}

/** 全部 AI 动态（聚合条目 + 分类标签统计） */
export async function loadAll(): Promise<AllFeedResponse | null> {
  if (STATIC_SITE) {
    const snap = await loadSnapshot();
    return snap?.all || null;
  }
  try {
    return await fetchJSON<AllFeedResponse>(publicAsset("api/all"));
  } catch {
    const snap = await loadSnapshot();
    return snap?.all || null;
  }
}

/** 官方历史日报完整内容（含版块与条目），失败返回 null */
export async function loadDailyReport(date: string): Promise<DailyReport | null> {
  if (STATIC_SITE) {
    const snap = await loadSnapshot();
    return snap?.dailyReports?.[date] || null;
  }
  try {
    const data = await fetchJSON<{ report?: DailyReport }>(`${publicAsset("api/daily")}?date=${encodeURIComponent(date)}`);
    return data.report ?? null;
  } catch {
    return null;
  }
}

/** 周报期刊数据（public/weekly/{weekStart}.json），classification 归一化为前端格式 */
export async function loadWeeklyJournal(weekStart: string): Promise<WeeklyJournal | null> {
  try {
    const data = await fetchJSON<WeeklyJournal>(publicAsset(`weekly/${encodeURIComponent(weekStart)}.json`));
    data.items = (data.items || []).map((it) => {
      const raw = it.classification as { category?: string } | undefined;
      return raw?.category
        ? { ...it, classification: { ...it.classification, cat: raw.category, catLabel: it.classification?.catLabel || raw.category } }
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
    return await fetchJSON<ItemsPage>(`${publicAsset("api/items")}?${params}`);
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
    fundingTableCache = await fetchJSON<FundingTable>(publicAsset("funding-table.json"));
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
    companyOverviewCache = await fetchJSON<CompanyOverview>(publicAsset("company-overview.json"));
  } catch {
    companyOverviewCache = null;
  }
  companyOverviewLoaded = true;
  return companyOverviewCache;
}

/** 从快照生成精选条目池；新版快照优先使用 featured，旧快照回退 daily+weekly。 */
export function poolFromSnapshot(snap: Snapshot): NewsItem[] {
  if (snap.featured?.length) {
    return [...snap.featured].sort(
      (a, b) => new Date(b.publishedAt || 0).getTime() - new Date(a.publishedAt || 0).getTime(),
    );
  }
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
