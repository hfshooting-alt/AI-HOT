// 展示层工具：北京时间格式化、六版块归一化、配色（与 build_snapshot.py 口径一致）
import type { NewsItem } from "../domain/types";

/** 六版块固定顺序（与后端 SECTIONS 对应） */
export const SECTIONS = [
  "模型发布/更新",
  "产品发布/更新",
  "AI泛娱乐新闻",
  "行业动态",
  "论文研究",
  "技巧与观点",
] as const;

/** aihot API 英文分类 -> 中文六版块 */
export const API_CATEGORY_MAP: Record<string, string> = {
  "ai-models": "模型发布/更新",
  "ai-products": "产品发布/更新",
  industry: "行业动态",
  paper: "论文研究",
  tip: "技巧与观点",
};

/** 六版块短名（精选页分类 Tab 用） */
export const SECTION_SHORT: Record<string, string> = {
  "模型发布/更新": "模型",
  "产品发布/更新": "产品",
  AI泛娱乐新闻: "泛娱乐",
  行业动态: "行业",
  论文研究: "论文",
  技巧与观点: "观点",
};

/** 六版块配色（与后端 SECTION_COLORS 对应） */
export const SECTION_COLORS: Record<string, string> = {
  "模型发布/更新": "#6366f1",
  "产品发布/更新": "#10b981",
  AI泛娱乐新闻: "#ec4899",
  行业动态: "#f59e0b",
  论文研究: "#f43f5e",
  技巧与观点: "#06b6d4",
};

const WEEKDAYS = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];

const CN_DIGITS = "〇一二三四五六七八九";

/** 1-99 -> 中文数字（日报期刊头用，与后端 cn_num 同口径） */
export function cnNum(n: number): string {
  if (n < 10) return CN_DIGITS[n];
  const tens = Math.floor(n / 10);
  const rem = n % 10;
  if (tens === 1) return "十" + (rem ? CN_DIGITS[rem] : "");
  return CN_DIGITS[tens] + "十" + (rem ? CN_DIGITS[rem] : "");
}

/** 2026-08-18 -> 二〇二六年八月十八日 */
export function fmtCnDate(iso?: string): string {
  const d = bjDate(iso);
  if (!d) return "";
  const year = String(d.getUTCFullYear())
    .split("")
    .map((c) => CN_DIGITS[Number(c)])
    .join("");
  return `${year}年${cnNum(d.getUTCMonth() + 1)}月${cnNum(d.getUTCDate())}日`;
}

/** 英文分类归一化为中文六版块；已是中文版块名则直通 */
export function normalizeCategory(cat?: string): string {
  if (!cat) return "行业动态";
  if ((SECTIONS as readonly string[]).includes(cat)) return cat;
  return API_CATEGORY_MAP[cat] || "行业动态";
}

/** ISO8601 -> 北京时刻度（用 UTC getter 读取北京时间分量） */
export function bjDate(iso?: string): Date | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return new Date(t + 8 * 3600 * 1000);
}

/** 北京时区日期键 YYYY-MM-DD（用于按日分组） */
export function bjDayKey(iso?: string): string {
  const d = bjDate(iso);
  if (!d) return "";
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

/** "08:01" */
export function fmtClock(iso?: string): string {
  const d = bjDate(iso);
  if (!d) return "";
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** "8月18日" */
export function fmtMonthDay(iso?: string): string {
  const d = bjDate(iso);
  if (!d) return "";
  return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日`;
}

/** "星期二" */
export function fmtWeekday(iso?: string): string {
  const d = bjDate(iso);
  if (!d) return "";
  return WEEKDAYS[d.getUTCDay()];
}

/** "2026年8月18日星期二" */
export function fmtFullDay(iso?: string): string {
  const d = bjDate(iso);
  if (!d) return "";
  return `${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月${d.getUTCDate()}日 ${fmtWeekday(iso)}`;
}

/** 相对时间："3 小时前 / 2 天前"（热点榜用） */
export function fmtRelative(iso?: string): string {
  const d = bjDate(iso);
  if (!d) return "";
  const now = Date.now() + 8 * 3600 * 1000;
  const diffMs = now - d.getTime();
  const hours = Math.floor(diffMs / 3600000);
  if (hours < 1) return "1 小时内";
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return fmtMonthDay(iso);
}

/** 条目展示时间：快照带 timeText 时优先，否则按北京时间格式 "8/18 08:01" */
export function fmtItemTime(item: NewsItem): string {
  const d = bjDate(item.publishedAt);
  if (!d) return item.timeText || "";
  const now = new Date(Date.now() + 8 * 3600 * 1000);
  const hm = fmtClock(item.publishedAt);
  if (d.toDateString() === now.toDateString()) return `今天 ${hm}`;
  if (new Date(now.getTime() - 86400000).toDateString() === d.toDateString()) return `昨天 ${hm}`;
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${hm}`;
}

/** 条目跳转链接：原文优先，缺省回退 permalink */
export function itemUrl(item: NewsItem): string {
  return item.url || item.permalink || "#";
}
