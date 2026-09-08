// 来源类型判定与搜索匹配：纯函数，供精选 / 全部 AI 动态两个视图共用
// AI HOT API 无结构化来源类型字段，采用启发式规则（URL 域名 + 来源名特征），
// 判定顺序：公众号 → 推文 → 资讯 → 一手信源（兜底）。媒体清单可随时增补。

export type SourceKind = "direct" | "media" | "tweet" | "wechat";

export const SOURCE_KIND_LABELS: Record<SourceKind, string> = {
  direct: "一手信源",
  media: "资讯",
  tweet: "推文",
  wechat: "公众号",
};

export const SOURCE_KIND_ORDER: SourceKind[] = ["direct", "media", "tweet", "wechat"];

/** 资讯类媒体域名黑名单（url 域名命中即判为「资讯」；按需增补） */
export const MEDIA_HOSTS: string[] = [
  "ithome.com",
  "arstechnica.com",
  "the-decoder.com",
  "theverge.com",
  "36kr.com",
  "jiqizhixin.com",
  "huxiu.com",
  "geekpark.net",
  "qbitai.com",
  "leiphone.com",
  "ifanr.com",
  "pingwest.com",
  "cnbeta.com",
  "solidot.org",
];

/** 资讯类媒体名称特征（source 字符串命中即判为「资讯」） */
export const MEDIA_NAME_MARKERS: string[] = [
  "IT之家",
  "Hacker News",
  "Ars Technica",
  "The Decoder",
  "36氪",
  "机器之心",
  "虎嗅",
  "极客公园",
  "量子位",
  "雷锋网",
  "爱范儿",
  "品玩",
  "CnBeta",
];

const WECHAT_HOSTS = ["mp.weixin.qq.com"];
const TWEET_HOSTS = ["x.com", "twitter.com"];

interface SourceCandidate {
  source?: string;
  sourceType?: string;
  url?: string;
  permalink?: string;
}

/** 从 url/permalink 解析主机名（去 www. 前缀，小写） */
export function hostOf(candidate: SourceCandidate): string {
  const raw = candidate.url || candidate.permalink || "";
  try {
    return (new URL(raw).hostname || "").replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

/** 来源类型判定（顺序：公众号 → 推文 → 资讯 → 一手信源兜底） */
export function sourceKindOf(item: SourceCandidate): SourceKind {
  const host = hostOf(item);
  const source = item.source || "";
  if (item.sourceType === "wechat" || source.startsWith("公众号：") || WECHAT_HOSTS.includes(host)) {
    return "wechat";
  }
  if (TWEET_HOSTS.includes(host) || source.includes("X：")) {
    return "tweet";
  }
  if (MEDIA_HOSTS.includes(host) || MEDIA_NAME_MARKERS.some((m) => source.includes(m))) {
    return "media";
  }
  return "direct";
}

export interface SearchableItem extends SourceCandidate {
  title?: string;
  summary?: string;
  mpName?: string | null;
}

/** 搜索匹配：标题 + 摘要 + 来源名 + 公众号名 + URL 小写包含匹配 */
export function matchItem(item: SearchableItem, kw: string): boolean {
  const query = kw.trim().toLowerCase();
  if (!query) return true;
  const hay = [
    item.title || "",
    item.summary || "",
    item.source || "",
    item.mpName || "",
    item.url || "",
    item.permalink || "",
  ]
    .join(" ")
    .toLowerCase();
  return hay.includes(query);
}
