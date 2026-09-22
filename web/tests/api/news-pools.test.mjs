import assert from "node:assert/strict";
import test from "node:test";
import { poolFromSnapshot, shouldLoadLiveNews, shouldMergeReviewedNews } from "../../app/_lib/data/news-pools.ts";
import { categoryOf, matchDims, TAXONOMY_LABELS } from "../../app/_lib/domain/taxonomy.ts";

const old = { id: "aihot:old", title: "旧文章", publishedAt: "2026-09-21T10:00:00+08:00" };
const raw = { id: "manus:raw", title: "电子纸采访", publishedAt: "2026-09-22T09:11:00+08:00", selected: true, score: 99 };
const curated = { id: "aihot:curated", title: "融资报道", publishedAt: "2026-09-21T20:00:00+08:00", selected: false, score: 1,
  classification: { cat: "financing", catLabel: "融资动态" } };
const legacy = { daily: { sections: [{ items: [old] }] }, weekly: { sections: [{ items: [old, curated] }] } };

test("separate pools keep raw articles and financing without treating upstream score or selected as Garena selection", () => {
  const snapshot = { ...legacy, newsSelectionVersion: 1, publicationMode: "pipeline",
    all: { items: [old, curated, raw] }, garenaSelected: { items: [curated] } };
  const before = structuredClone(snapshot);
  assert.deepEqual(poolFromSnapshot(snapshot).map(x => x.id), [raw.id, curated.id, old.id]);
  assert.deepEqual(poolFromSnapshot(snapshot, "selected"), [curated]);
  assert.equal(categoryOf(curated), "financing");
  assert.deepEqual(snapshot, before);
});

test("explicit empty or malformed new selection never resurrects all or historical digests", () => {
  for (const selection of [{ garenaSelected: { items: [] } }, { garenaSelected: null }, {}]) {
    const snapshot = { ...legacy, newsSelectionVersion: 1, all: { items: [raw] }, ...selection };
    assert.deepEqual(poolFromSnapshot(snapshot, "selected"), []);
    assert.equal(shouldMergeReviewedNews(snapshot), false);
  }
  assert.deepEqual(poolFromSnapshot({ ...legacy, garenaSelected: { items: [] } }, "selected"), []);
});

test("an explicitly empty all pool and missing pipeline pool do not borrow old daily or weekly items", () => {
  assert.deepEqual(poolFromSnapshot({ ...legacy, all: { items: [] } }), []);
  assert.deepEqual(poolFromSnapshot({ ...legacy, publicationMode: "pipeline" }), []);
  assert.deepEqual(poolFromSnapshot({ ...legacy, newsSelectionVersion: 1 }), []);
});

test("legacy snapshots retain their already-screened all pool and oldest digest fallback", () => {
  assert.deepEqual(poolFromSnapshot({ ...legacy, all: { items: [old] } }, "selected"), [old]);
  assert.deepEqual(poolFromSnapshot(legacy, "selected"), [curated, old]);
  assert.deepEqual(poolFromSnapshot(legacy), [curated, old]);
  assert.equal(shouldMergeReviewedNews(legacy), true);
});

test("live data and legacy supplements cannot alter either new authoritative pool", () => {
  const snapshot = { ...legacy, newsSelectionVersion: 1, all: { items: [raw] }, garenaSelected: { items: [curated] } };
  for (const mode of ["all", "selected"]) {
    assert.equal(shouldLoadLiveNews(snapshot, mode), false);
    assert.equal(shouldLoadLiveNews({ publicationMode: "pipeline" }, mode), false);
  }
  assert.equal(shouldLoadLiveNews(null, "selected"), false);
  assert.equal(shouldLoadLiveNews(legacy, "selected"), false);
  assert.equal(shouldLoadLiveNews(legacy, "all"), true);
  assert.equal(shouldMergeReviewedNews(snapshot), false);
  assert.equal(shouldMergeReviewedNews({ garenaSelected: { items: [] } }), false);
});

test("raw articles without summary or classification remain readable and are labelled unclassified", () => {
  assert.deepEqual(poolFromSnapshot({ newsSelectionVersion: 1, all: { items: [raw] } }), [raw]);
  assert.equal(categoryOf(raw), "unclassified");
  assert.equal(TAXONOMY_LABELS[categoryOf(raw)], "未分类");
  assert.equal(categoryOf({ ...raw, category: "行业动态", categoryUnclassified: true }), "unclassified");
  assert.equal(categoryOf({ ...raw, category: "行业动态" }), "general");
  assert.equal(categoryOf({ ...raw, categoryUnclassified: true, classification: { cat: "interview" } }), "interview");
  assert.equal(matchDims(raw, {}), true);
});
