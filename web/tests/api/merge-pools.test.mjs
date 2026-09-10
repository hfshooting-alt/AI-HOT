import assert from "node:assert/strict";
import test from "node:test";
import { mergePools } from "../../app/_lib/data/merge-pools.ts";

test("upstream classification cannot replace the site's reviewed classification", () => {
  const result = mergePools([{ id: "aihot:c", classification: { cat: "bigtech" }, classificationOrigin: "deepseek-review" }],
    [{ id: "c", classification: { cat: "release" } }]);
  assert.equal(result[0].classification.cat, "bigtech");
  assert.equal(result[0].classificationOrigin, "deepseek-review");
});

test("merging a static snapshot with itself does not duplicate Manus news", () => {
  const items = [{ id: "manus:a" }, { id: "wechat:b" }, { id: "aihot:c" }];
  assert.deepEqual(mergePools(items, items).map(item => item.id), items.map(item => item.id));
});

test("raw AIHOT IDs match the snapshot and preserve classification", () => {
  const classification = { cat: "release" };
  const result = mergePools([{ id: "aihot:c", title: "old", classification }],
    [{ id: "c", title: "updated" }]);
  assert.deepEqual(result, [{ id: "aihot:c", title: "updated", classification }]);
});
