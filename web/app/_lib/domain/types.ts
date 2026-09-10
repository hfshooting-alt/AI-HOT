// AI HOT 前端数据类型定义（与 build_snapshot.py / aihot API 对齐）

export type ViewKey = "all" | "company" | "hot" | "daily" | "settings";

/** AI 两级分类（tag_news 打标签产物，展示结构；dims 与 to_display 输出对齐） */
export interface Classification {
  cat: string;
  catLabel: string;
  dims?: { label: string; value: string }[];
}

/** 新闻条目（快照与 aihot API 合并后的统一结构） */
export interface NewsItem {
  id: string;
  title: string;
  summary?: string;
  url?: string;
  permalink?: string;
  source?: string;
  sourceType?: "aihot" | "wechat" | "media" | "direct";
  sourceChannel?: "wechat_original" | "tencent_syndication" | "netease_syndication" | "publisher_site" | "media_page";
  /** 中文六版块；API 原始英文分类经 API_CATEGORY_MAP 归一化 */
  category?: string;
  /** 上游没有返回分类时为 true；展示层会暂时归入泛行业新闻并明确提示。 */
  categoryUnclassified?: boolean;
  publishedAt?: string;
  discoveredAt?: string;
  score?: number | null;
  selected?: boolean;
  mpName?: string | null;
  classification?: Classification | null;
  num?: number;
  timeText?: string;
  /** AIHOT v1 的站内 canonical 与第三方原文，便于保留来源层级。 */
  aihotUrl?: string;
  originalUrl?: string;
  reason?: string | null;
  timeBasis?: "published" | "discovered";
}

/** AIHOT /api/v1/items 的原始条目。 */
export interface AIHotV1Item {
  id: string;
  title: string;
  originalTitle: string | null;
  summary: string | null;
  source: { name: string };
  links: { aihot: string; original: string };
  publishedAt: string | null;
  discoveredAt: string;
  category: string | null;
  score: number | null;
  selected: boolean;
  reason: string | null;
}

export interface DigestSection {
  label: string;
  count: number;
  items: NewsItem[];
}

/** 日报 / 周报视图（快照 DATA.daily / DATA.weekly 结构） */
export interface DigestView {
  view: string;
  range: { start: string; end: string; label: string; cnLabel?: string };
  total: number;
  lead?: string | null;
  sections: DigestSection[];
  stats: { label: string; count: number }[];
  mpStatus?: { connected: boolean; note?: string };
  generatedAt: string;
  vol?: string;
}

/** 主页历史归档日期导航条目 */
export interface HistoryEntry {
  date: string;
  label: string;
  title: string;
  total: number;
  finalized: boolean;
  url: string;
}

/** 自然周期刊导航条目 */
export interface WeeklyNavEntry {
  url: string;
  label: string;
  range: string;
  total: number;
}

/** build_snapshot.py 输出的 snapshot.json 根结构 */
export interface Snapshot {
  daily: DigestView;
  weekly: DigestView;
  history: HistoryEntry[];
  /** AIHOT 每日约 08:00 发布的成品日报索引。 */
  dailyHistory?: HistoryEntry[];
  weeklyNav: WeeklyNavEntry[];
  /** 静态托管降级数据；Pages 无服务端 API 时直接读取。 */
  hot?: Partial<HotTopicsResponse> & { items: HotTopic[] };
  all?: AllFeedResponse;
  /** 静态站点内嵌的日报正文；键为 YYYY-MM-DD。 */
  dailyReports?: Record<string, DailyReport>;
}

/** /api/daily 上游日报条目（无 id/score/分类标签） */
export interface DailyReportItem {
  title: string;
  summary?: string;
  source?: { name?: string };
  links?: { aihot?: string; original?: string };
}

/** /api/daily 上游日报响应（report 包裹层） */
export interface DailyReport {
  date: string;
  generatedAt?: string;
  lead?: { title?: string; summary?: string } | null;
  sections: { label: string; items: DailyReportItem[] }[];
  flashes?: DailyReportItem[];
  links?: { aihot?: string };
}

/** public/weekly/{date}.json 周报期刊 */
export interface WeeklyJournal {
  weekStart: string;
  weekEnd: string;
  volLabel: string;
  finalized: boolean;
  aiReport?: unknown | null;
  items: NewsItem[];
}

/** /api/v1/hot-topics 单条热点事件（实测结构） */
export interface HotTopic {
  rank: number;
  id: string;
  title: string;
  source: { name: string };
  links: { aihot: string; original: string; story: string };
  sourceCount: number;
  signalCount: number;
  sourceNames: string[];
  latestAt: string;
}

export interface HotTopicsResponse {
  schemaVersion: number;
  count: number;
  items: HotTopic[];
}

/** /api/v1/items 分页响应 */
export interface ItemsPage {
  schemaVersion: number;
  items: AIHotV1Item[];
  page: {
    count: number;
    hasMore: boolean;
    nextCursor: string | null;
  };
}

/** /api/all 聚合响应（条目 + 分类标签统计） */
export interface AllFeedResponse {
  items: NewsItem[];
  tags: { tag: string; count: number }[];
  live: boolean;
}

/** 融资表格单行：一家公司/产品（scripts/funding_table.py 产物，public/funding-table.json） */
export interface FundingCompany {
  id: string;
  company_name: string;
  product_name: string | null;
  founded: string | null;
  country: string | null;
  industry: string | null;
  team: string | null;
  business: string | null;
  investors: string | null;
  total_funding: string | null;
  valuation: string | null;
  /** 筛选标签（维度中文 label → 取值，与 classification.dims 对齐） */
  dims?: Record<string, string>;
  /** 经联网搜索补全的字段名 */
  filledBySearch?: string[];
  /** 搜索补全来源 URL */
  searchSources?: string[];
  /** 来源文章（publishedAt 倒序，[0] 为最新） */
  sourceArticles: {
    id: string;
    title: string;
    url: string;
    publishedAt: string;
    mpName: string;
  }[];
}

/** 融资表格根结构（构建时离线生成，非实时） */
export interface FundingTable {
  schemaVersion: number;
  generatedAt: string;
  coverageNote?: string;
  searchNote?: string;
  stats: {
    articlesProcessed: number;
    extractionFailed?: number;
    articlesWithoutFundingInfo?: number;
    companiesTotal: number;
    companiesSearched?: number;
  };
  companies: FundingCompany[];
}

export interface CompanyFieldEvidence {
  value: string;
  articleId: string;
  url: string;
  title: string;
  publishedAt: string;
  sourceName: string;
  origin: "article" | "research";
  quote?: string;
  checkedAt?: string;
}

/** 全类别新闻共同沉淀的公司/产品档案。 */
export interface CompanyProfile {
  brandProfiles?: Record<string, CompanyProfile>;
  id: string;
  company_name: string;
  aliases: string[];
  product_names: string[];
  founded: string | null;
  country: string | null;
  team: string | null;
  business: string | null;
  investors: string | null;
  total_funding: string | null;
  valuation: string | null;
  dims: Record<string, string>;
  fieldSources: Record<string, CompanyFieldEvidence[]>;
  sourceArticles: {
    id: string;
    title: string;
    url: string;
    publishedAt: string;
    sourceName: string;
    category: string;
  }[];
  firstSeenAt: string;
  lastSeenAt: string;
}

export interface CompanyOverview {
  schemaVersion: number;
  generatedAt: string;
  coverageNote: string;
  stats: {
    articlesProcessed: number;
    articlesComplete: number;
    articlesFailed: number;
    articlesDeferred: number;
    modelCalls: number;
    cacheHits: number;
    companiesTotal: number;
    productsTotal: number;
  };
  companies: CompanyProfile[];
}
