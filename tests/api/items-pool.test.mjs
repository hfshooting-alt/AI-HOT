import assert from "node:assert/strict";
import test from "node:test";
import { fetchItemsPool } from "../../app/_lib/data/items-pool.ts";

test("first-page failure differs from a successful empty page", async () => {
  assert.deepEqual(await fetchItemsPool(async () => ({ ok: false, status: 502 })),
    { items: [], live: false });
  assert.deepEqual(await fetchItemsPool(async () => ({ ok: true, data: { items: [] } })),
    { items: [], live: true });
});

test("later-page failure preserves items and forwards the encoded cursor", async () => {
  const paths = [];
  const result = await fetchItemsPool(async (path) => {
    paths.push(path);
    return paths.length === 1
      ? { ok: true, data: { items: [{ id: "a" }], hasNext: true, nextCursor: "a+b /" } }
      : { ok: false, status: 503 };
  });
  assert.deepEqual(result, { items: [{ id: "a" }], live: true });
  assert.deepEqual(paths, ["/api/public/items?limit=50", "/api/public/items?limit=50&cursor=a%2Bb+%2F"]);
});

test("pagination stops at three pages and retains upstream order and duplicates", async () => {
  let calls = 0;
  const result = await fetchItemsPool(async () => {
    calls++;
    return { ok: true, data: { items: [{ id: "same" }], hasNext: true, nextCursor: String(calls) } };
  });
  assert.equal(calls, 3);
  assert.deepEqual(result.items, [{ id: "same" }, { id: "same" }, { id: "same" }]);
});

test("a missing cursor or false hasNext ends pagination", async () => {
  for (const page of [{ hasNext: true }, { hasNext: false, nextCursor: "unused" }]) {
    let calls = 0;
    assert.deepEqual(await fetchItemsPool(async () => {
      calls++;
      return { ok: true, data: page };
    }), { items: [], live: true });
    assert.equal(calls, 1);
  }
});
