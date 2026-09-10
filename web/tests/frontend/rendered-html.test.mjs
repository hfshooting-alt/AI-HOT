// rendered-html.test.mjs — 构建产物冒烟：dist Worker 能启动并渲染真实 AppShell；
// 同时校验 page/layout 无脚手架骨架（SkeletonPreview）残留引用。
// 运行：npm run build && node --test tests/frontend/rendered-html.test.mjs
import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const templateRoot = new URL("../../", import.meta.url);

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

test("navigation defaults to all news and exposes company overview as the second page", async () => {
  const [provider, sidebar, shell] = await Promise.all([
    readFile(new URL("../../app/_components/providers/AppDataProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../app/_components/layout/Sidebar.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../app/_components/layout/AppShell.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(provider, /return "all"/);
  assert.match(provider, /replaceState\(null, "", normalizedHash\)/);
  assert.doesNotMatch(provider, /featured/);
  assert.ok(sidebar.indexOf("全部 AI 动态") < sidebar.indexOf("公司与产品全景"));
  assert.doesNotMatch(sidebar, /精选|京ICP备2026012723号-2/);
  assert.match(sidebar, /Garena投资部专用/);
  assert.doesNotMatch(sidebar, /数据来源：AIHOT 开放 API/);
  assert.match(shell, /panel\("company", <CompanyOverviewView \/>\)/);
  assert.doesNotMatch(shell, /FeaturedView|featured/);
});

test("company database exposes filterable industry and country fields below its title", async () => {
  const [view, table] = await Promise.all([
    readFile(new URL("../../app/_components/views/CompanyOverviewView.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../app/_components/company/CompanyOverviewTable.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(view, /"行业"/);
  assert.match(view, /"国家 \/ 地区"/);
  assert.match(table, /key: "industry", label: "行业"/);
  assert.match(table, /key: "country", label: "国家 \/ 地区"/);
  assert.ok(table.indexOf("公司与产品情报库") < table.indexOf("<TagFilterBar"));
  assert.match(table, /dims=\{\["industry", "region"\]\}/);
});

test("stale funding output falls back to the refreshed news stream", async () => {
  const view = await readFile(new URL("../../app/_components/views/AllAIView.tsx", import.meta.url), "utf8");
  assert.match(view, /Garena投资部专用/);
  assert.doesNotMatch(view, /数据来源：AIHOT 开放 API/);
  assert.match(view, /fundingStale/);
  assert.match(view, /结构化融资表等待模型更新，本轮先展示当前资讯流/);
  assert.match(view, /wantTable && !fundingStale/);
});
