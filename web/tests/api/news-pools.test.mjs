import assert from "node:assert/strict";
import test from "node:test";
import { poolFromSnapshot, newsPoolError } from "../../app/_lib/data/news-pools.ts";
import { categoryOf, matchDims, TAXONOMY_LABELS } from "../../app/_lib/domain/taxonomy.ts";

const old = { id: "aihot:old", title: "旧文章", publishedAt: "2026-09-21T10:00:00+08:00" };
const raw = { id: "manus:raw", title: "电子纸采访", publishedAt: "2026-09-22T09:11:00+08:00", selected: true, score: 99 };
const curated = { id: "manus:curated", title: "融资报道", publishedAt: "2026-09-21T20:00:00+08:00", selected: false, score: 1,
  classification: { cat: "financing", catLabel: "融资动态" } };
const historical = { daily: { sections: [{ items: [old, raw] }] }, weekly: { sections: [{ items: [old, curated] }] } };

test("only Manus articles remain in each independent pool, including financing and unclassified metadata", () => {
  const snapshot = { ...historical, newsSelectionVersion: 1, publicationMode: "pipeline",
    all: { items: [old, curated, raw] }, garenaSelected: { items: [old, curated] } };
  const before = structuredClone(snapshot);
  assert.deepEqual(poolFromSnapshot(snapshot), [raw, curated]);
  assert.deepEqual(poolFromSnapshot(snapshot, "selected"), [curated]);
  assert.equal(categoryOf(curated), "financing");
  assert.deepEqual(snapshot, before);
});

test("explicit empty pools remain empty even with live, selected or historical alternatives", () => {
  for (const mode of ["all", "selected"]) {
    const snapshot = { ...historical, all: { items: [raw] }, garenaSelected: { items: [curated] },
      [mode === "all" ? "all" : "garenaSelected"]: { items: [] } };
    assert.deepEqual(poolFromSnapshot(snapshot, mode), []);
    assert.equal(newsPoolError(snapshot, mode), null);
  }
});

test("missing new and legacy pools never fall back to another view or historical batch", () => {
  for (const version of [undefined, 1]) {
    assert.deepEqual(poolFromSnapshot({ ...historical, newsSelectionVersion: version }), []);
    const snapshot = { ...historical, newsSelectionVersion: version, all: { items: [raw] } };
    assert.deepEqual(poolFromSnapshot(snapshot, "selected"), []);
    assert.match(newsPoolError(snapshot, "selected"), /数据不完整/);
  }
});

test("failed or malformed snapshots show an explicit error distinct from no articles", () => {
  assert.match(newsPoolError(null), /暂不可用/);
  for (const all of [undefined, null, {}, { items: null }, { items: {} }, { items: [null] }, { items: [{ id: 1, title: "bad" }] }]) {
    assert.deepEqual(poolFromSnapshot({ all }), []);
    assert.match(newsPoolError({ all }), /数据/);
  }
  assert.equal(newsPoolError({ all: { items: [] } }), null);
});

test("publisher and channel labels cannot turn other collectors into Manus", () => {
  const snapshot = { all: { items: [
    { ...old, source: "Manus", sourceType: "wechat" },
    { ...old, id: "wechat:legacy", source: "公众号：机器之心" },
    { ...old, id: "demo:sample" },
    { ...raw, sourceType: "media" },
    { ...curated, sourceType: "wechat" },
  ] } };
  assert.deepEqual(poolFromSnapshot(snapshot).map(item => item.id), [raw.id, curated.id]);
});

test("raw Manus without summary or classification is preserved and labelled unclassified", () => {
  assert.deepEqual(poolFromSnapshot({ all: { items: [raw] } }), [raw]);
  assert.equal(categoryOf(raw), "unclassified");
  assert.equal(TAXONOMY_LABELS[categoryOf(raw)], "未分类");
  assert.equal(categoryOf({ ...raw, category: "行业动态", categoryUnclassified: true }), "unclassified");
  assert.equal(matchDims(raw, {}), true);
});

test("date and relative publication precision are preserved without moving the fixed batch window", () => {
  const yesterday = { ...raw, id: "manus:yesterday", publishedAt: "2026-09-21", publishedPrecision: "date",
    timeEvidence: { originalText: "昨天", observedAt: "2026-09-22T17:00:00+08:00" } };
  const snapshot = { all: { items: [yesterday, raw] } };
  const result = poolFromSnapshot(snapshot);
  assert.deepEqual(result, [raw, yesterday]);
  assert.deepEqual(result[1].timeEvidence, yesterday.timeEvidence);
  assert.equal(result[1].publishedPrecision, "date");
});
