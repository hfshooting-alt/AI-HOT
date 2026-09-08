// 服务端共享：aihot 上游 API 代理工具（仅被 app/api/* 路由引用）
export const AIHOT_BASE = "https://aihot.virxact.com";

export type UpstreamResult =
  | { ok: true; data: unknown }
  | { ok: false; status: number };

/** 抓取上游 JSON；网络失败返回 502，上游非 2xx 透传状态码 */
export async function upstreamJSON(path: string): Promise<UpstreamResult> {
  try {
    const r = await fetch(AIHOT_BASE + path, {
      headers: { accept: "application/json" },
    });
    if (!r.ok) return { ok: false, status: r.status };
    return { ok: true, data: await r.json() };
  } catch {
    return { ok: false, status: 502 };
  }
}
