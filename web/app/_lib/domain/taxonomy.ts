// 新闻分类与处理状态；处理状态不冒充 taxonomy 中的新闻类别。
import type { NewsItem } from "./types";

/** 新 6 类（展示顺序固定；dims 为该类别的并列筛选维度 id；display 对齐 taxonomy.json） */
export const TAXONOMY_CATEGORIES = [
  { id: "financing", label: "融资动态", dims: ["industry", "region"], display: "table" },
  { id: "interview", label: "深度访谈", dims: ["industry", "interviewee"], display: "card" },
  { id: "release", label: "产品和模型发布", dims: ["industry", "issuer"], display: "card" },
  { id: "paper", label: "论文研究", dims: [], display: "card" },
  { id: "bigtech", label: "大厂动态", dims: ["change_type", "company"], display: "card" },
  { id: "general", label: "泛行业新闻", dims: [], display: "card" },
] as const;

/** 类别内容呈现形式：table=公司维度表格（融资动态），card=文章卡片流 */
export function categoryDisplay(catId: string): "table" | "card" {
  return TAXONOMY_CATEGORIES.find((c) => c.id === catId)?.display ?? "card";
}

/** 维度定义（label/value 与 classification.dims 的中文 label 直接匹配） */
export const TAXONOMY_DIMENSIONS: Record<string, { label: string; values: string[] }> = {
  industry: {
    label: "行业",
    values: ["游戏引擎", "AI社交/陪伴", "AI游戏内容", "AI互动内容/社区", "AI模型", "其他AI应用"],
  },
  region: { label: "国家/地区", values: ["中国", "美国", "欧洲", "东南亚", "日韩", "其他"] },
  interviewee: { label: "访谈对象", values: ["创始人/CEO", "产品经理", "算法/泛技术", "投资人", "其他"] },
  issuer: { label: "发布主体", values: ["创业公司", "大厂/非创业公司", "其他"] },
  change_type: { label: "类型", values: ["人事变动", "业务线变化", "其他"] },
  company: {
    label: "公司",
    values: ["字节跳动", "阿里巴巴", "美团", "腾讯", "OpenAI", "Anthropic", "Google", "Meta", "其他"],
  },
};

/** 新 6 类配色 */
export const TAXONOMY_CATEGORY_COLORS: Record<string, string> = {
  financing: "#10b981",
  interview: "#8b5cf6",
  release: "#6366f1",
  paper: "#f43f5e",
  bigtech: "#f59e0b",
  general: "#06b6d4",
  awaiting_body: "#b45309",
  classification_pending: "#64748b",
  classification_failed: "#dc2626",
  unclassified: "#94a3b8",
};

/** 仅在当前文章池中存在时显示；保持分类、来源与搜索筛选可组合。 */
export const ARTICLE_STATUS_FILTERS = [
  { id: "awaiting_body", label: "待正文" },
  { id: "classification_pending", label: "待打标" },
  { id: "classification_failed", label: "打标失败" },
  { id: "unclassified", label: "未分类" },
] as const;

/** 分类 id -> 中文名 */
export const TAXONOMY_LABELS: Record<string, string> = {
  ...Object.fromEntries(TAXONOMY_CATEGORIES.map((c) => [c.id, c.label])),
  ...Object.fromEntries(ARTICLE_STATUS_FILTERS.map((status) => [status.id, status.label])),
};

/** 旧六版块 -> 新 6 类兜底映射（无 classification 的条目：尚未打标条目） */
const LEGACY_CATEGORY_MAP: Record<string, string> = {
  "模型发布/更新": "release",
  "产品发布/更新": "release",
  AI泛娱乐新闻: "general",
  行业动态: "general",
  论文研究: "paper",
  技巧与观点: "general",
};

/** 条目分类归属：classification.cat 优先，旧六版块 category 兜底映射 */
export function categoryOf(item: NewsItem): string {
  if (item.contentStatus === "awaiting_body") return "awaiting_body";
  if (item.classificationStatus === "failed") return "classification_failed";
  if (item.classificationStatus === "pending") return "classification_pending";
  const cat = item.classification?.cat;
  if (cat && TAXONOMY_CATEGORIES.some((category) => category.id === cat)) return cat;
  if (item.categoryUnclassified) return "unclassified";
  return LEGACY_CATEGORY_MAP[item.category || ""] || "unclassified";
}

/** 分类已完成但摘要尚未完成时保留真实类别，并说明摘要状态。 */
export function summaryStatusLabel(item: NewsItem): string | null {
  if (item.contentStatus === "awaiting_body" || item.classificationStatus !== "complete") return null;
  if (item.summaryStatus === "failed") return "摘要失败";
  if (item.summaryStatus === "pending") return "待摘要";
  return null;
}

/** 条目所属类别可用的维度标签集：{维度label: 条目值} */
export function dimsOf(item: NewsItem): Record<string, string> {
  const out: Record<string, string> = {};
  for (const d of item.classification?.dims || []) {
    if (d?.label && d?.value) out[d.label] = d.value;
  }
  return out;
}

/** 维度标签筛选：维度内 OR、维度间 AND（selection 为空表示不筛） */
export function matchDims(item: NewsItem, selection: Record<string, string[]>): boolean {
  const active = Object.entries(selection).filter(([, vals]) => vals.length > 0);
  if (!active.length) return true;
  const dims = dimsOf(item);
  for (const [dimLabel, vals] of active) {
    const itemVal = dims[dimLabel];
    if (!itemVal || !vals.includes(itemVal)) return false;
  }
  return true;
}
