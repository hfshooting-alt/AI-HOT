// 浏览器只读取已发布的 Manus 批次；缺失数据返回空态，不请求外部新闻 API。
import type { CompanyOverview, FundingTable, Snapshot } from "../domain/types";

/** 保留现有 GitHub Pages 的 /AI-HOT/ 部署路径。 */
function publicAsset(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  return `${base}${path.replace(/^\//, "")}`;
}

async function fetchJSON<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-cache", headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  return (await response.json()) as T;
}

/** 最新发布批次；读取失败由视图明确显示，不从历史或演示数据补齐。 */
export async function loadSnapshot(): Promise<Snapshot | null> {
  try {
    const value = await fetchJSON<Snapshot>(publicAsset("snapshot.json"));
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

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

/** 已发布公司库是唯一权威，不追加旧批次的浏览器补录。 */
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

export { poolFromSnapshot, newsPoolError } from "./news-pools";
