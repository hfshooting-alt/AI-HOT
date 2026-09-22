// 客户端数据层：快照 + 本站 API 代理 + 降级策略
// 优先级：/snapshot.json（构建产物）→ /api/*（服务端代理 aihot API）→ 空态
import type {
  AllFeedResponse,
  CompanyOverview,
  DailyReport,
  FundingTable,
  HotTopicsResponse,
  ItemsPage,
  Snapshot,
  WeeklyJournal,
} from "../domain/types";
import { mergeReviewedCompanies } from "./reviewed-news.mjs";

/** 兼容站点根目录与 GitHub Pages 的 /AI-HOT/ 子路径。 */
function publicAsset(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  return `${base}${path.replace(/^\//, "")}`;
}

const STATIC_SITE = import.meta.env.VITE_STATIC_SITE === "true";

async function fetchJSON<T>(url: string): Promise<T> {
  // Revalidate mutable JSON after a Pages deployment instead of using a fresh
  // browser-cache entry from the previous published batch.
  const r = await fetch(url, { cache: "no-cache", headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return (await r.json()) as T;
}

/** 构建时生成的快照数据（全部动态 / 日报周报索引的数据源） */
export async function loadSnapshot(): Promise<Snapshot | null> {
  try {
    return await fetchJSON<Snapshot>(publicAsset("snapshot.json"));
  } catch {
    return null;
  }
}

/** 单篇审核补录独立于定时采集批次，缺失时不影响主新闻流。 */
export async function loadReviewedNews(): Promise<unknown> {
  try {
    return await fetchJSON<unknown>(publicAsset("reviewed-news.json"));
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
    const [overview, reviewed] = await Promise.all([
      fetchJSON<CompanyOverview>(publicAsset("company-overview.json")), loadReviewedNews(),
    ]);
    companyOverviewCache = mergeReviewedCompanies(overview, reviewed);
  } catch {
    companyOverviewCache = null;
  }
  companyOverviewLoaded = true;
  return companyOverviewCache;
}

export { poolFromSnapshot, shouldLoadLiveNews, shouldMergeReviewedNews } from "./news-pools";
export { mergePools } from "./merge-pools";
