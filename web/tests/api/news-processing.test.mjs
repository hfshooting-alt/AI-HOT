import assert from "node:assert/strict";
import test from "node:test";
import { ARTICLE_STATUS_FILTERS, categoryOf, matchDims, summaryStatusLabel, TAXONOMY_LABELS } from "../../app/_lib/domain/taxonomy.ts";
import { matchItem } from "../../app/_lib/display/source.ts";

const article = { id: "manus:test", title: "游戏产业观察", source: "腾讯新闻转载：媒体", sourceType: "media", sourceChannel: "tencent_syndication" };
const classification = { cat: "general", catLabel: "泛行业新闻", dims: [] };

test("missing body displays awaiting body and cannot inherit a guessed or stale category", () => {
  const item = { ...article, contentStatus: "awaiting_body", classificationStatus: "pending", summaryStatus: "pending",
    category: "行业动态", classification };
  assert.equal(categoryOf(item), "awaiting_body");
  assert.equal(TAXONOMY_LABELS[categoryOf(item)], "待正文");
  assert.equal(summaryStatusLabel(item), null);
});

test("available body distinguishes unprocessed classification from a failed model result", () => {
  const pending = { ...article, contentStatus: "available", classificationStatus: "pending" };
  const failed = { ...pending, classificationStatus: "failed", classification };
  assert.equal(TAXONOMY_LABELS[categoryOf(pending)], "待打标");
  assert.equal(TAXONOMY_LABELS[categoryOf(failed)], "打标失败");
  assert.equal(categoryOf(article), "unclassified");
  assert.equal(categoryOf({ ...article, classification: { cat: "made_up" } }), "unclassified");
});

test("a classified article keeps its category even when it is not an investment selection", () => {
  const item = { ...article, contentStatus: "available", classificationStatus: "complete", summaryStatus: "complete",
    classification, garenaSelection: { status: "not_selected" }, selected: false };
  assert.equal(categoryOf(item), "general");
  assert.equal(summaryStatusLabel(item), null);
  assert.equal(categoryOf({ ...item, summaryStatus: "failed" }), "general");
  assert.equal(summaryStatusLabel({ ...item, summaryStatus: "failed" }), "摘要失败");
  assert.equal(summaryStatusLabel({ ...item, summaryStatus: "pending" }), "待摘要");
});

test("processing status filtering composes with text and dimension filters", () => {
  const waiting = { ...article, contentStatus: "awaiting_body", classificationStatus: "pending" };
  const failed = { ...article, id: "manus:failed", contentStatus: "available", classificationStatus: "failed" };
  const classified = { ...article, id: "manus:complete", classificationStatus: "complete", classification };
  const items = [waiting, failed, classified];
  const selected = items.filter(item => categoryOf(item) === "awaiting_body"
    && matchItem(item, "游戏") && matchDims(item, {}));
  assert.deepEqual(selected, [waiting]);
  assert.equal(items.filter(item => categoryOf(item) === "general").length, 1);
  assert.deepEqual(ARTICLE_STATUS_FILTERS.filter(status => items.some(item => categoryOf(item) === status.id))
    .map(status => status.label), ["待正文", "打标失败"]);
});
