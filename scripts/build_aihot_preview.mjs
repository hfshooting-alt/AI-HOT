/** Build a local-only frontend snapshot from previously fetched AIHOT v1 review data. */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) args.set(process.argv[index], process.argv[index + 1]);

const inputDir = resolve(projectRoot, args.get("--input") || "work/aihot-preview/latest");
const baselinePath = resolve(projectRoot, args.get("--baseline") || "web/public/snapshot.json");
const outputPath = resolve(projectRoot, args.get("--output") || "work/aihot-preview/site/snapshot.json");
const workRoot = resolve(projectRoot, "work");
const outputRelative = relative(workRoot, outputPath);
if (outputRelative.startsWith("..") || isAbsolute(outputRelative)) {
  throw new Error("AIHOT review snapshot must stay under the ignored work/ directory.");
}

const readJSON = (path) => JSON.parse(readFileSync(path, "utf8"));
const categoryMap = {
  "ai-models": "模型发布/更新",
  "ai-products": "产品发布/更新",
  industry: "行业动态",
  paper: "论文研究",
  tip: "技巧与观点",
};

function normalizeItem(item) {
  const publishedAt = item.publishedAt || item.discoveredAt;
  return {
    id: `aihot:${item.id}`,
    title: item.title,
    summary: item.summary || "",
    source: item.source?.name || "AIHOT",
    sourceType: String(item.source?.name || "").startsWith("公众号：") ? "wechat" : "aihot",
    category: categoryMap[item.category] || "行业动态",
    categoryUnclassified: !item.category,
    publishedAt,
    discoveredAt: item.discoveredAt,
    timeBasis: item.publishedAt ? "published" : "discovered",
    score: typeof item.score === "number" ? item.score : null,
    selected: Boolean(item.selected),
    reason: item.reason || null,
    url: item.links?.original || item.links?.aihot || "",
    permalink: item.links?.aihot || item.links?.original || "",
    originalUrl: item.links?.original || "",
    aihotUrl: item.links?.aihot || "",
  };
}

const baseline = readJSON(baselinePath);
const allItems = readJSON(resolve(inputDir, "all-24h.json")).items.map(normalizeItem);
const hot = readJSON(resolve(inputDir, "hot-topics.json"));
const dailyEnvelope = readJSON(resolve(inputDir, "daily-latest.json"));
const report = dailyEnvelope.report;
const total = [...(report.sections || []), { items: report.flashes || [] }]
  .reduce((sum, section) => sum + (section.items?.length || 0), 0);
const [, month, day] = report.date.split("-").map(Number);
const weekday = new Intl.DateTimeFormat("zh-CN", { weekday: "long", timeZone: "Asia/Shanghai" })
  .format(new Date(`${report.date}T00:00:00+08:00`));
const firstItem = report.lead || report.sections?.flatMap((section) => section.items || [])[0];
const historyEntry = {
  date: report.date,
  label: `${month}月${day}日 ${weekday}`,
  title: firstItem?.title || "AIHOT 日报",
  total,
  finalized: true,
  url: report.links?.aihot || "",
};
const tags = Object.entries(Object.groupBy(allItems, (item) => item.category || "未分类"))
  .map(([tag, items]) => ({ tag, count: items.length }));

const snapshot = {
  ...baseline,
  hot,
  all: { items: allItems, tags, live: true },
  history: [historyEntry, ...(baseline.history || []).filter((entry) => entry.date !== report.date)],
  dailyReports: { ...(baseline.dailyReports || {}), [report.date]: report },
  preview: {
    localOnly: true,
    generatedAt: new Date().toISOString(),
    window: "24h",
    allCount: allItems.length,
  },
};

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, JSON.stringify(snapshot), "utf8");
console.log(`Local AIHOT preview snapshot: ${allItems.length} all, ${hot.items?.length || 0} hot, daily ${report.date}.`);
