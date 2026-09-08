import assert from "node:assert/strict";
import test from "node:test";

test("built all/featured routes preserve filtering, normalization and failure responses", async () => {
  const originalFetch = globalThis.fetch;
  let fail = false;
  globalThis.fetch = async () => fail
    ? new Response("Unavailable", { status: 503 })
    : Response.json({ items: [
      { id: "older", title: "Alpha", summary: "keyword", selected: true, source: "公众号：甲", publishedAt: "2026-08-20" },
      { id: "newer", title: "Beta", selected: false, source: "媒体", publishedAt: "2026-08-21" },
    ] });
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
    assert.deepEqual(data.tags, [{ tag: "行业动态", count: 2 }]);
    assert.equal(data.live, true);
    const featured = await request("/api/featured?q=KEYWORD&category=" + encodeURIComponent("行业动态"));
    assert.deepEqual((await featured.json()).items.map((it) => it.id), ["aihot:older"]);
    assert.equal(featured.headers.get("cache-control"), "s-maxage=60, stale-while-revalidate=300");
    assert.deepEqual((await (await request("/api/featured?q=missing")).json()).items, []);
    fail = true;
    const failedAll = await request("/api/all");
    assert.deepEqual(await failedAll.json(), { items: [], tags: [], live: false });
    assert.equal(failedAll.headers.get("cache-control"), "s-maxage=60, stale-while-revalidate=300");
    const failedFeatured = await request("/api/featured");
    assert.equal(failedFeatured.status, 200);
    assert.deepEqual(await failedFeatured.json(), { items: [], live: false });
    assert.equal(failedFeatured.headers.get("cache-control"), null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
