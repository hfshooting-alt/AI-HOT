import assert from "node:assert/strict";
import test from "node:test";
import { fetchItemsPool } from "../../app/_lib/data/items-pool.ts";

test("first-page failure differs from a successful empty page", async () => {
  assert.deepEqual(await fetchItemsPool(async () => ({ ok: false, status: 502 })),
    { items: [], live: false });
  assert.deepEqual(await fetchItemsPool(async () => ({ ok: true, data: { items: [], page: { hasMore: false, nextCursor: null } } })),
    { items: [], live: true });
});

test("later-page failure preserves items and forwards the encoded cursor", async () => {
  const paths = [];
  const result = await fetchItemsPool(async (path) => {
    paths.push(path);
    return paths.length === 1
      ? { ok: true, data: { items: [{ id: "a" }], page: { hasMore: true, nextCursor: "a+b /" } } }
      : { ok: false, status: 503 };
  });
  assert.deepEqual(result, { items: [{ id: "a" }], live: true });
  assert.deepEqual(paths, [
    "/api/v1/items?mode=all&window=7d&by=timeline&limit=100",
    "/api/v1/items?mode=all&window=7d&by=timeline&limit=100&cursor=a%2Bb+%2F",
  ]);
});

test("pagination stops at three pages and retains upstream order and duplicates", async () => {
  let calls = 0;
  const result = await fetchItemsPool(async () => {
    calls++;
    return { ok: true, data: { items: [{ id: "same" }], page: { hasMore: true, nextCursor: String(calls) } } };
  });
  assert.equal(calls, 3);
  assert.deepEqual(result.items, [{ id: "same" }, { id: "same" }, { id: "same" }]);
});

test("a missing cursor or false hasMore ends pagination", async () => {
  for (const page of [{ hasMore: true }, { hasMore: false, nextCursor: "unused" }]) {
    let calls = 0;
    assert.deepEqual(await fetchItemsPool(async () => {
      calls++;
      return { ok: true, data: { items: [], page } };
    }), { items: [], live: true });
    assert.equal(calls, 1);
  }
});
