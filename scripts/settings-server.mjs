#!/usr/bin/env node
// settings-server.mjs — AI HOT 本地设置服务（仅绑定 127.0.0.1，局域网不可达）
//
// 用途：Next.js 设置页（SettingsView）通过 HTTP 读写项目根 .env，
//       让 MANUS_API_KEY / DEEPSEEK_API_KEY / TAVILY_API_KEY / LLM_API_BASE /
//       LLM_MODEL / MANUS_AGENT_PROFILE 在本地流水线（build_snapshot.py /
//       manus runner / funding_table.py）中免手动 export 即生效
//       （Python 侧由 llm_common / manus_source.config 读取）。
//
// 安全边界：
//   - 只监听回环地址，只允许配置的浏览器来源（CORS）；
//   - 密钥永不回显明文（GET /api/status 只返回 set + 尾 4 位）；
//   - .env 已被 .gitignore 忽略，不会入库；写前保留一份 .env.bak。
//
// 用法:
//   node scripts/settings-server.mjs
//   AIHOT_SETTINGS_PORT=9732 node scripts/settings-server.mjs
//   AIHOT_SETTINGS_FILE=/abs/path/.env node scripts/settings-server.mjs   # 测试/自定义
//   AIHOT_CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000" node scripts/settings-server.mjs
//
// 纯 Node 标准库，无第三方依赖。导出 createSettingsServer 供 tests/test_settings_server.mjs 复用。
import { createServer } from "node:http";
import { copyFile, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 9731;
const DEFAULT_ENV_FILE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  ".env",
);
const DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"];

// 密钥类变量：状态接口只回显尾 4 位，永不回明文。
const SECRET_KEYS = new Set(["MANUS_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY"]);
const KEY_RE = /^[A-Z][A-Z0-9_]*$/;
const MAX_BODY_BYTES = 64 * 1024;

/** 读取 .env 为 Map（仅收录合法变量名，注释/空行跳过）。 */
async function readEnvMap(envFile) {
  const map = new Map();
  if (!existsSync(envFile)) return map;
  const text = await readFile(envFile, "utf8");
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const i = line.indexOf("=");
    const key = line.slice(0, i).trim();
    if (!KEY_RE.test(key)) continue;
    map.set(key, line.slice(i + 1).trim());
  }
  return map;
}

/** 按 key 精确替换/新增/删除；注释与未知变量行原样保留。 */
function renderEnv(map, originalText) {
  const lines = originalText ? originalText.split(/\r?\n/) : [];
  const out = [];
  const seen = new Set();
  for (const raw of lines) {
    const line = raw.trim();
    if (line && !line.startsWith("#") && line.includes("=")) {
      const i = line.indexOf("=");
      const key = line.slice(0, i).trim();
      if (KEY_RE.test(key)) {
        if (map.has(key)) {
          out.push(`${key}=${map.get(key)}`);
          seen.add(key);
        }
        continue; // 已删除的 key 跳过原行
      }
    }
    out.push(raw);
  }
  for (const [key, value] of map) {
    if (!seen.has(key)) out.push(`${key}=${value}`);
  }
  return out.join("\n");
}

function json(res, status, payload) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new Error("请求体过大（上限 64KB）"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

/** 创建设置服务（不自动监听，供测试注入临时文件与端口）。 */
export function createSettingsServer({
  host = DEFAULT_HOST,
  port = DEFAULT_PORT,
  envFile = DEFAULT_ENV_FILE,
  allowedOrigins = DEFAULT_ORIGINS,
} = {}) {
  const origins = new Set(allowedOrigins.map((s) => String(s).trim()).filter(Boolean));

  return createServer(async (req, res) => {
    const origin = req.headers.origin;
    const originAllowed = origin === undefined || origins.has(origin);

    const applyCors = () => {
      if (origin !== undefined && origins.has(origin)) {
        res.setHeader("Access-Control-Allow-Origin", origin);
        res.setHeader("Vary", "Origin");
        res.setHeader("Access-Control-Allow-Methods", "GET, PUT, OPTIONS");
        res.setHeader("Access-Control-Allow-Headers", "Content-Type");
      }
    };

    if (req.method === "OPTIONS") {
      if (!originAllowed) return json(res, 403, { error: "来源不被允许" });
      applyCors();
      res.writeHead(204);
      res.end();
      return;
    }
    if (!originAllowed) return json(res, 403, { error: "来源不被允许" });

    try {
      const url = new URL(req.url ?? "/", `http://${host}:${port}`);

      if (req.method === "GET" && url.pathname === "/healthz") {
        applyCors();
        return json(res, 200, { ok: true, file: envFile });
      }

      if (req.method === "GET" && url.pathname === "/api/status") {
        const map = await readEnvMap(envFile);
        const status = {};
        for (const [key, value] of map) {
          status[key] = SECRET_KEYS.has(key)
            ? { set: true, tail: String(value).slice(-4) }
            : { set: true, value };
        }
        applyCors();
        return json(res, 200, { ok: true, status });
      }

      if (req.method === "PUT" && url.pathname === "/api/settings") {
        let body;
        try {
          body = JSON.parse(await readBody(req));
        } catch (err) {
          return json(res, 400, { error: `请求体不是合法 JSON：${err.message}` });
        }
        const values = body?.values;
        if (!values || typeof values !== "object" || Array.isArray(values)) {
          return json(res, 400, { error: "缺少 values 对象" });
        }
        const map = await readEnvMap(envFile);
        for (const [key, value] of Object.entries(values)) {
          if (!KEY_RE.test(key)) {
            return json(res, 400, { error: `非法变量名（仅允许大写字母/数字/下划线）：${key}` });
          }
          const text = typeof value === "string" ? value : String(value ?? "");
          const trimmed = text.trim();
          if (trimmed.includes("\n") || trimmed.includes("\r")) {
            return json(res, 400, { error: `${key} 的值不能包含换行` });
          }
          if (trimmed === "") map.delete(key);
          else map.set(key, trimmed);
        }
        const originalText = existsSync(envFile) ? await readFile(envFile, "utf8") : "";
        if (existsSync(envFile)) {
          await copyFile(envFile, `${envFile}.bak`).catch(() => {});
        }
        await writeFile(envFile, renderEnv(map, originalText), "utf8");

        const status = {};
        for (const [key, value] of map) {
          status[key] = SECRET_KEYS.has(key)
            ? { set: true, tail: String(value).slice(-4) }
            : { set: true, value };
        }
        applyCors();
        return json(res, 200, { ok: true, status });
      }

      return json(res, 404, { error: "not found" });
    } catch (err) {
      return json(res, 500, { error: String(err?.message || err) });
    }
  });
}

function main() {
  const port = Number(process.env.AIHOT_SETTINGS_PORT || DEFAULT_PORT);
  const envFile = path.resolve(process.env.AIHOT_SETTINGS_FILE || DEFAULT_ENV_FILE);
  const allowedOrigins = (process.env.AIHOT_CORS_ORIGINS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const server = createSettingsServer({
    host: DEFAULT_HOST,
    port,
    envFile,
    allowedOrigins: allowedOrigins.length ? allowedOrigins : DEFAULT_ORIGINS,
  });
  server.on("error", (err) => {
    if (err.code === "EADDRINUSE") {
      console.error(
        `[settings-server] 端口 ${port} 已被占用：可能已有实例在运行，` +
          `或用 AIHOT_SETTINGS_PORT=9732 换端口`,
      );
    } else {
      console.error(`[settings-server] 启动失败：${err.message}`);
    }
    process.exit(1);
  });
  server.listen(port, DEFAULT_HOST, () => {
    console.log(`[settings-server] 监听 http://${DEFAULT_HOST}:${port}（.env: ${envFile}）`);
    console.log(`[settings-server] 启动 Next.js 设置页后即可在「设置」视图保存密钥`);
  });
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  main();
}
