import assert from "node:assert/strict";
import test from "node:test";
import { viewFromHash } from "../../app/_lib/domain/navigation.ts";

test("retired settings bookmarks and unknown routes open all articles", () => {
  for (const hash of ["#/settings", "#settings", "#/settings?tab=model", "#/daily", "#/hot", "#/unknown", "", "#/"]) {
    assert.equal(viewFromHash(hash), "all", hash);
  }
  assert.equal(viewFromHash(), "all");
});

test("article, selection and company bookmarks keep their current destination", () => {
  for (const view of ["all", "selected", "company"]) {
    assert.equal(viewFromHash(`#/${view}`), view);
    assert.equal(viewFromHash(`#${view}`), view);
  }
});
