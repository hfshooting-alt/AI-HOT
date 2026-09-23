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

/** 历史英文分类 -> 中文六版块 */
export const API_CATEGORY_MAP: Record<string, string> = {
  "ai-models": "模型发布/更新",
  "ai-products": "产品发布/更新",
  industry: "行业动态",
  paper: "论文研究",
  tip: "技巧与观点",
};

/** 六版块短名（全部动态分类 Tab 用） */
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

/** Company dates retain source precision; never invent a month/day. */
export function fmtCompanyDate(value?: string | null): string {
  if (!value) return "";
  const digits = "零一二三四五六七八九";
  const numeric = value.replace(/[〇零一二三四五六七八九十]+/g, (part) => {
    if (!part.includes("十")) return [...part].map(c => c === "〇" ? "0" : String(digits.indexOf(c))).join("");
    const [a, b] = part.split("十");
    return String((a ? digits.indexOf(a) : 1) * 10 + (b ? digits.indexOf(b) : 0));
  });
  const full = numeric.match(/^(\d{4})年(\d{1,2})月(\d{1,2})日$/);
  if (full) return `${full[1]}-${full[2].padStart(2, "0")}-${full[3].padStart(2, "0")}`;
  const month = numeric.match(/^(\d{4})年(\d{1,2})月$/);
  if (month) return `${month[1]}-${month[2].padStart(2, "0")}`;
  return /^\d{4}$/.test(numeric) ? `${numeric}年` : numeric;
}

export function fmtCompanyFounded(value?: string | null, evidence: { value?: string; quote?: string; dateBasis?: string; legalEntity?: string; verificationStatus?: string }[] = []): string {
  const date = fmtCompanyDate(value);
  if (!date) return "";
  const matching = evidence.filter(e => !e.value || fmtCompanyDate(e.value) === date);
  if (matching.length && matching.every(e => e.verificationStatus === 'provisional')) return `${date}（暂定，注册日期待核实）`;
  const registered = evidence.find(e => (!e.value || fmtCompanyDate(e.value) === date) && (e.dateBasis === "registration" || /incorporated|注册成立|注册日期|登记成立|成立登记/i.test(e.quote || "")));
  return registered ? `${date}${registered.legalEntity ? `（${registered.legalEntity}）` : ""}` : `${date}（创立口径，注册日期待核实）`;
}

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
  // Legacy wall-clock values must not depend on the viewer's computer timezone.
  const value = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00+08:00`
    : /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(iso)
      ? `${iso.replace(" ", "T")}+08:00` : iso;
  const t = new Date(value).getTime();
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

/** 条目展示时间：快照带 timeText 时优先，否则按北京时间格式 "8/18 08:01" */
export function fmtItemTime(item: NewsItem): string {
  if (item.publishedPrecision === "date") return `${item.publishedAt || ""} · ${item.timeEvidence?.originalText === "昨天" ? "原文标注昨天，" : ""}具体时刻未披露`;
  if (item.publishedPrecision === "relative" && item.timeEvidence) return `${item.publishedAt?.slice(0, 10) || ""} · 采集时标注${item.timeEvidence.originalText}（估算）`;
  const d = bjDate(item.publishedAt);
  if (!d) return item.timeText || "";
  const now = new Date(Date.now() + 8 * 3600 * 1000);
  const hm = fmtClock(item.publishedAt);
  const day = (value: Date) => value.toISOString().slice(0, 10);
  if (day(d) === day(now)) return `今天 ${hm}`;
  if (day(new Date(now.getTime() - 86400000)) === day(d)) return `昨天 ${hm}`;
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${hm}`;
}

/** 条目跳转链接：原文优先，缺省回退 permalink */
export function itemUrl(item: NewsItem): string {
  return item.url || item.permalink || "#";
}
