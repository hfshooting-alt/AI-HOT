import assert from "node:assert/strict";
import test from "node:test";

test("built all route preserves normalization, ordering and failure responses", async () => {
  const originalFetch = globalThis.fetch;
  let fail = false;
  globalThis.fetch = async () => fail
    ? new Response("Unavailable", { status: 503 })
    : Response.json({ items: [
      { id: "older", title: "Alpha", summary: "keyword", selected: true, source: { name: "公众号：甲" }, links: { original: "https://example.com/a", aihot: "https://aihot.news/items/older" }, category: null, publishedAt: "2026-08-20", discoveredAt: "2026-08-20", score: 70, reason: null, originalTitle: null },
      { id: "newer", title: "Beta", summary: null, selected: false, source: { name: "媒体" }, links: { original: "https://example.com/b", aihot: "https://aihot.news/items/newer" }, category: null, publishedAt: "2026-08-21", discoveredAt: "2026-08-21", score: null, reason: null, originalTitle: null },
    ], page: { count: 2, hasMore: false, nextCursor: null } });
  // vinext 捕获导入时的 fetch，因此先安装替身再加载构建产物。
  const { default: worker } = await import("../../dist/server/index.js");
  const request = (path) => worker.fetch(new Request(`http://localhost${path}`), {}, {
    waitUntil() {}, passThroughOnException() {},
  });
  try {
    const all = await request("/api/all");
    const data = await all.json();
    assert.deepEqual(data.items.map((it) => it.id), ["aihot:newer", "aihot:older"]);
    assert.deepEqual(data.items.map((it) => it.sourceType), ["aihot", "wechat"]);
    assert.deepEqual(data.items.map((it) => it.categoryUnclassified), [true, true]);
    assert.deepEqual(data.tags, [{ tag: "行业动态", count: 2 }]);
    assert.equal(data.live, true);
    fail = true;
    const failedAll = await request("/api/all");
    assert.deepEqual(await failedAll.json(), { items: [], tags: [], live: false });
    assert.equal(failedAll.headers.get("cache-control"), "s-maxage=60, stale-while-revalidate=300");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
