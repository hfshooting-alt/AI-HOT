// rendered-html.test.mjs — 构建产物冒烟：dist Worker 能启动并渲染真实 AppShell；
// 同时校验 page/layout 无脚手架骨架（SkeletonPreview）残留引用。
// 运行：npm run build && node --test tests/frontend/rendered-html.test.mjs
import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const templateRoot = new URL("../..", import.meta.url);

async function render() {
  const workerUrl = new URL("../../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the AI HOT app shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  // layout 元信息与 AppShell 客户端挂载前的占位根节点（SSR 阶段 mounted=false）
  assert.match(html, /<html lang="zh-CN"/);
  assert.match(html, /AI HOT · AI 情报仪表盘/);
  assert.match(html, /min-h-screen bg-page/);
});

test("page renders the real AppShell without starter skeleton leftovers", async () => {
  const [page, layout] = await Promise.all([
    readFile(new URL("../../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../app/layout.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(page, /from "\.\/_components\/layout\/AppShell"/);
  assert.match(page, /<AppShell \/>/);
  assert.doesNotMatch(page, /SkeletonPreview|codex-preview|_sites-preview/);

  assert.match(layout, /title:\s*"AI HOT · AI 情报仪表盘"/);
  assert.doesNotMatch(layout, /SkeletonPreview|codex-preview|_sites-preview/);

  await assert.rejects(
    access(new URL("public/_sites-preview", templateRoot)),
  );
});
