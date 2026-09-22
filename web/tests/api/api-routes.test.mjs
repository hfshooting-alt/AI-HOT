import assert from "node:assert/strict";
import test from "node:test";

test("retired external-news APIs return 404 and never contact an upstream", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async input => {
    calls.push(String(input));
    throw new Error("External HTTP is forbidden in this regression");
  };
  try {
    const { default: worker } = await import("../../dist/server/index.js");
    for (const path of ["/api/all", "/api/items?cursor=old", "/api/daily?date=2026-09-22", "/api/hot"]) {
      const response = await worker.fetch(new Request(`http://localhost${path}`), {
        ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
      }, { waitUntil() {}, passThroughOnException() {} });
      assert.equal(response.status, 404, path);
    }
    assert.deepEqual(calls, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
