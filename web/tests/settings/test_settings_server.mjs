// test_settings_server.mjs — 本地设置服务离线单测（随机端口 + 临时 .env 文件）
// 运行：node --test tests/settings/test_settings_server.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile, access } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createSettingsServer } from "../../../scripts/settings-server.mjs";

const ALLOWED_ORIGIN = "http://localhost:3000";

async function withServer(t) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "settings-server-test-"));
  const envFile = path.join(dir, ".env");
  const server = createSettingsServer({ port: 0, envFile, allowedOrigins: [ALLOWED_ORIGIN] });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const base = `http://127.0.0.1:${port}`;
  t.after(async () => {
    await new Promise((resolve) => server.close(resolve));
    await rm(dir, { recursive: true, force: true });
  });
  return { base, envFile };
}

async function jsonFetch(url, init) {
  const r = await fetch(url, init);
  const data = await r.json();
  return { status: r.status, headers: r.headers, data };
}

test("healthz 返回 ok", async (t) => {
  const { base } = await withServer(t);
  const r = await fetch(`${base}/healthz`);
  assert.equal(r.status, 200);
  const data = await r.json();
  assert.equal(data.ok, true);
});

test("初始状态为空，密钥写入后只回显掩码尾 4 位", async (t) => {
  const { base } = await withServer(t);
  const before = await jsonFetch(`${base}/api/status`);
  assert.deepEqual(before.data.status, {});

  const put = await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { MANUS_API_KEY: "sk-secret-9876", DEEPSEEK_API_KEY: "sk-ds-abcd" } }),
  });
  assert.equal(put.status, 200);
  assert.equal(put.data.status.MANUS_API_KEY.tail, "9876");
  assert.equal(put.data.status.DEEPSEEK_API_KEY.tail, "abcd");

  // 明文绝不出现在任何响应中
  const text = JSON.stringify(put.data);
  assert.ok(!text.includes("sk-secret-9876"), "响应泄露明文 MANUS_API_KEY");
  assert.ok(!text.includes("sk-ds-abcd"), "响应泄露明文 DEEPSEEK_API_KEY");

  const after = await jsonFetch(`${base}/api/status`);
  assert.equal(after.data.status.MANUS_API_KEY.tail, "9876");
  assert.ok(!JSON.stringify(after.data).includes("sk-secret-9876"));
});

test("非密钥变量回显原值，空字符串删除条目", async (t) => {
  const { base, envFile } = await withServer(t);
  await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { LLM_API_BASE: "https://api.deepseek.com", MANUS_API_KEY: "sk-x" } }),
  });
  let text = await readFile(envFile, "utf8");
  assert.match(text, /LLM_API_BASE=https:\/\/api\.deepseek\.com/);

  const put2 = await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { MANUS_API_KEY: "", LLM_API_BASE: "https://other.example.com" } }),
  });
  assert.equal(put2.status, 200);
  assert.equal(put2.data.status.MANUS_API_KEY, undefined);
  text = await readFile(envFile, "utf8");
  assert.ok(!text.includes("MANUS_API_KEY"), "空字符串应删除该 key");
  assert.match(text, /LLM_API_BASE=https:\/\/other\.example\.com/);
});

test("非法变量名与换行值被拒绝", async (t) => {
  const { base, envFile } = await withServer(t);
  const badName = await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { "bad-name": "x" } }),
  });
  assert.equal(badName.status, 400);

  const badValue = await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { DEEPSEEK_API_KEY: "a\nb" } }),
  });
  assert.equal(badValue.status, 400);

  // 被拒绝的写入不得创建/污染 .env 文件
  await assert.rejects(readFile(envFile, "utf8"), { code: "ENOENT" });
});

test("注释与未知变量行在重写后保留", async (t) => {
  const { base, envFile } = await withServer(t);
  await writeFile(
    envFile,
    "# 顶部注释\n# MANUS_API_KEY=commented-out\nSOME_OTHER_VAR=keep\n",
    "utf8",
  );
  const put = await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { MANUS_API_KEY: "sk-new" } }),
  });
  assert.equal(put.status, 200);
  const text = await readFile(envFile, "utf8");
  assert.match(text, /# 顶部注释/);
  assert.match(text, /# MANUS_API_KEY=commented-out/);
  assert.match(text, /SOME_OTHER_VAR=keep/);
  assert.match(text, /MANUS_API_KEY=sk-new/);
});

test("首次写入生成 .env.bak 备份", async (t) => {
  const { base, envFile } = await withServer(t);
  await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { LLM_MODEL: "v1" } }),
  });
  await jsonFetch(`${base}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Origin: ALLOWED_ORIGIN },
    body: JSON.stringify({ values: { LLM_MODEL: "v2" } }),
  });
  await access(`${envFile}.bak`);
  const bak = await readFile(`${envFile}.bak`, "utf8");
  assert.match(bak, /LLM_MODEL=v1/);
  const cur = await readFile(envFile, "utf8");
  assert.match(cur, /LLM_MODEL=v2/);
});

test("CORS：允许的来源带响应头，非允许来源被拒绝", async (t) => {
  const { base } = await withServer(t);
  const ok = await jsonFetch(`${base}/healthz`, { headers: { Origin: ALLOWED_ORIGIN } });
  assert.equal(ok.headers.get("access-control-allow-origin"), ALLOWED_ORIGIN);

  const denied = await jsonFetch(`${base}/healthz`, { headers: { Origin: "http://evil.example.com" } });
  assert.equal(denied.status, 403);
});

test("PUT 预检（OPTIONS）对允许来源返回 204 与 CORS 头", async (t) => {
  const { base } = await withServer(t);
  const r = await fetch(`${base}/api/settings`, {
    method: "OPTIONS",
    headers: { Origin: ALLOWED_ORIGIN, "Access-Control-Request-Method": "PUT" },
  });
  assert.equal(r.status, 204);
  assert.equal(r.headers.get("access-control-allow-origin"), ALLOWED_ORIGIN);
  assert.match(r.headers.get("access-control-allow-methods") || "", /PUT/);
});

test("未知路径返回 404", async (t) => {
  const { base } = await withServer(t);
  const r = await fetch(`${base}/api/nope`);
  assert.equal(r.status, 404);
});
