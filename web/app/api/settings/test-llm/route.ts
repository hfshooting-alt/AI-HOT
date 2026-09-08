// 设置页「测试 LLM 连接」：把用户输入的 key/base/model 转发一次最小请求，密钥不落盘。
// 无状态、无缓存；成功返回耗时，失败返回服务商错误信息（截断）。
import { NextResponse } from "next/server";

interface TestBody {
  apiKey?: string;
  baseUrl?: string;
  model?: string;
}

const DEFAULT_BASE = "https://api.deepseek.com";
const DEFAULT_MODEL = "deepseek-chat";
const TIMEOUT_MS = 15_000;

export async function POST(request: Request) {
  let body: TestBody;
  try {
    body = (await request.json()) as TestBody;
  } catch {
    return NextResponse.json({ ok: false, error: "请求体不是合法 JSON" }, { status: 400 });
  }
  const apiKey = (body.apiKey || "").trim();
  const baseUrl = (body.baseUrl || "").trim() || DEFAULT_BASE;
  const model = (body.model || "").trim() || DEFAULT_MODEL;
  if (!apiKey) {
    return NextResponse.json({ ok: false, error: "缺少 API Key" }, { status: 400 });
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  const started = Date.now();
  try {
    const res = await fetch(`${baseUrl.replace(/\/+$/, "")}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model,
        temperature: 0,
        max_tokens: 8,
        messages: [{ role: "user", content: "ping" }],
      }),
      signal: ctrl.signal,
    });
    const text = await res.text();
    if (!res.ok) {
      let detail = "";
      try {
        const j = JSON.parse(text) as { error?: { message?: string } | string };
        detail = typeof j.error === "string" ? j.error : j.error?.message || "";
      } catch {
        detail = text.slice(0, 200);
      }
      return NextResponse.json(
        { ok: false, status: res.status, error: detail || `HTTP ${res.status}` },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    return NextResponse.json(
      { ok: true, latencyMs: Date.now() - started },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { ok: false, error: /abort/i.test(message) ? "连接超时（15 秒）" : message },
      { headers: { "Cache-Control": "no-store" } },
    );
  } finally {
    clearTimeout(timer);
  }
}
