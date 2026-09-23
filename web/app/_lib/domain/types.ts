// 新闻Daily 发布快照与公司产品库的数据类型。

export type NewsPoolMode = "all" | "selected";
export type ViewKey = NewsPoolMode | "company" | "settings";
export type ArticleProcessingStatus = "complete" | "pending" | "failed";

/** AI 两级分类（tag_news 打标签产物，展示结构；dims 与 to_display 输出对齐） */
export interface Classification {
  cat: string;
  catLabel: string;
  dims?: { label: string; value: string }[];
}

/** Manus 发布批次中的新闻条目。 */
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
  /** 上游没有返回分类时为 true；未经过本站分类的条目显示未分类。 */
  categoryUnclassified?: boolean;
  publishedAt?: string;
  publishedPrecision?: "datetime" | "date" | "relative";
  timeEvidence?: { originalText: string; observedAt: string } | null;
  discoveredAt?: string;
  /** 上游字段，不控制 Garena 投资精选的归属。 */
  score?: number | null;
  selected?: boolean;
  mpName?: string | null;
  classification?: Classification | null;
  classificationOrigin?: string;
  /** 正文与模型处理状态独立于是否进入投资精选；不据标题推断分类。 */
  contentStatus?: "available" | "awaiting_body";
  classificationStatus?: ArticleProcessingStatus;
  summaryStatus?: ArticleProcessingStatus;
  num?: number;
  timeText?: string;
  /** 原文链接。 */
  originalUrl?: string;
  reason?: string | null;
  timeBasis?: "published" | "discovered";
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
  collectionStatus?: {
    collectionWindow: { start: string; end: string; timezone: string };
    degraded: boolean;
    sources: { name: string; collector: string; reasonCode?: string; status: "complete" | "partial" | "failed" | "not_requested"; discoveredArticles: number; usableArticles: number }[];
    candidateArticles: number;
    publishedArticles: number;
    excludedArticles: number;
    quarantinedArticles?: number;
    quarantined?: { id: string; title: string; url: string; stage: string; reason: string }[];
  };
  publicationMode?: "pipeline";
  generatedAt?: string;
  daily?: DigestView;
  weekly?: DigestView;
  history?: HistoryEntry[];
  weeklyNav?: WeeklyNavEntry[];
  all?: AllFeedResponse;
  /** 两池契约：all 为已采集文章，garenaSelected 为本站筛选结果。 */
  newsSelectionVersion?: 1;
  garenaSelected?: AllFeedResponse;
}

/** 发布文章池（条目 + 分类标签统计）。 */
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
  dateBasis?: string;
  legalEntity?: string;
  asOf?: string;
  countryBasis?: string;
  verificationStatus?: "provisional" | "verified";
  reason?: string;
}

/** 全类别新闻共同沉淀的公司/产品档案。 */
export interface CompanyProfile {
  candidateOwners?: { name: string; reason: string; quote: string; url: string; checkedAt: string }[];
  entityType?: "company" | "product" | "brand" | "foundation" | "open_source_organization";
  entityTypeEvidence?: { url: string; quote: string; checkedAt: string };
  productUpdates?: { name: string; relationship: "owned" | "integrated" | "used" | "unknown"; quote: string; articleId: string; url: string; title: string; publishedAt: string; ownershipEvidence?: { url: string; title: string; quote: string; checkedAt: string } }[];
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
  updatedAt?: string;
  latestReportAt?: string;
  profileUpdatedAt?: string;
}

export interface CompanyOverview {
  pendingEntities?: CompanyProfile[];
  articleFailures?: { id: string; title: string; url: string; reason: string }[];
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
