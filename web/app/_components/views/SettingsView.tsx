// 设置视图：本地流水线 API Key 配置入口（本地专用；公开部署只读提示）
// 数据流：浏览器 ↔ 本地设置服务（127.0.0.1:9731，写项目根 .env）
//         浏览器 → /api/settings/test-llm（LLM 连接测试代理，密钥不落盘）
//         浏览器 → 剪贴板（GitHub Secrets 同步命令 / .env 内容）
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const SETTINGS_BASE = "http://127.0.0.1:9731";
const STORAGE_KEY = "aihot.settings.form.v1";
const REPO = "hfshooting-alt/AI-HOT";
const PROBE_TIMEOUT_MS = 1500;

interface KeyStatus {
  set: boolean;
  tail?: string;
  value?: string;
}

interface FieldDef {
  key: string;
  label: string;
  type: "password" | "text" | "select";
  secret: boolean;
  placeholder?: string;
  options?: string[];
  desc: string;
}

const FIELDS: FieldDef[] = [
  {
    key: "MANUS_API_KEY",
    label: "Manus API Key",
    type: "password",
    secret: true,
    placeholder: "sk-...",
    desc: "公众号采集（fetch-manus.yml / scripts/manus_source/runner.py）",
  },
  {
    key: "DEEPSEEK_API_KEY",
    label: "LLM API Key",
    type: "password",
    secret: true,
    placeholder: "sk-...",
    desc: "打标签 + 正文加工（tag_news.py / enrich_news.py），DeepSeek 或其他 OpenAI 兼容服务",
  },
  {
    key: "TAVILY_API_KEY",
    label: "Tavily API Key",
    type: "password",
    secret: true,
    placeholder: "tvly-...",
    desc: "融资表格缺失字段搜索补全（funding_table.py），tavily.com 免费注册（1000 credits/月）；未配置时留空不报错",
  },
  {
    key: "LLM_API_BASE",
    label: "LLM Base URL",
    type: "text",
    secret: false,
    placeholder: "https://api.deepseek.com",
    desc: "留空 = DeepSeek 默认；换服务商时填对应 API 地址（CI 用 repository variable LLM_API_BASE）",
  },
  {
    key: "LLM_MODEL",
    label: "LLM 模型名",
    type: "text",
    secret: false,
    placeholder: "deepseek-chat",
    desc: "留空 = taxonomy.json 的 model 默认；设置后自动使旧打标签缓存失效",
  },
  {
    key: "MANUS_AGENT_PROFILE",
    label: "Manus Agent Profile",
    type: "select",
    secret: false,
    options: ["manus-1.6-lite", "manus-1.6", "manus-1.6-max"],
    desc: "留空 = manus-1.6；降本可选手册里最便宜的 lite",
  },
];

const GH_SECRET_KEYS = ["MANUS_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY"];

function isLocalHost(): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h === "localhost" || h === "127.0.0.1" || h === "::1";
}

function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  // 非安全上下文（如 http 局域网）回退方案
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
  return Promise.resolve();
}

function buildEnvContent(values: Record<string, string>): string {
  const lines = [
    "# AI HOT 本地配置（由设置页生成；已被 .gitignore 忽略，勿提交）",
  ];
  for (const f of FIELDS) {
    const v = (values[f.key] || "").trim();
    if (f.type === "select" && f.key === "MANUS_AGENT_PROFILE" && !v) continue;
    lines.push(`# ${f.label}${f.desc ? " — " + f.desc : ""}`);
    lines.push(v ? `${f.key}=${v}` : `# ${f.key}=`);
  }
  return lines.join("\n") + "\n";
}

export function SettingsView() {
  const local = isLocalHost();
  const [online, setOnline] = useState<boolean | null>(null);
  const [status, setStatus] = useState<Record<string, KeyStatus>>({});
  // 浏览器记忆惰性恢复（仅本机；组件仅在客户端挂载，SSR 不执行）
  const [values, setValues] = useState<Record<string, string>>(() => {
    if (typeof window === "undefined" || !isLocalHost()) return {};
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? (JSON.parse(saved) as Record<string, string>) : {};
    } catch {
      return {};
    }
  });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "info"; text: string } | null>(null);
  const [interactiveGh, setInteractiveGh] = useState(false);
  const msgTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = useCallback((kind: "ok" | "err" | "info", text: string) => {
    if (msgTimer.current) clearTimeout(msgTimer.current);
    setMsg({ kind, text });
    msgTimer.current = setTimeout(() => setMsg(null), 6000);
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const r = await fetch(`${SETTINGS_BASE}/api/status`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as { status: Record<string, KeyStatus> };
      setStatus(data.status || {});
    } catch {
      setStatus({});
    }
  }, []);

  const OFFLINE_HINT = "本地设置服务未启动：请在项目目录（aihot-site，含 scripts/ 的目录）执行 node scripts/settings-server.mjs";

  /** 探测本地设置服务并刷新在线状态；返回清理函数（中止未完成的探测）。 */
  const probe = useCallback(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    fetch(`${SETTINGS_BASE}/healthz`, { signal: ctrl.signal })
      .then((r) => r.ok)
      .then((ok) => {
        setOnline(ok);
        if (ok) void loadStatus();
        else flash("info", OFFLINE_HINT);
      })
      .catch(() => {
        setOnline(false);
        flash("info", OFFLINE_HINT);
      })
      .finally(() => clearTimeout(timer));
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [flash, loadStatus]);

  // 挂载时探测；窗口重新聚焦时自动重探测（用户启动服务后切回浏览器即自动变在线）
  useEffect(() => {
    const cleanup = probe();
    const onFocus = () => {
      cleanup();
      probe();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      cleanup();
    };
  }, [probe]);

  // 表单变化：实时记忆（仅本机）
  useEffect(() => {
    if (!local) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
    } catch {
      /* 忽略写入失败 */
    }
  }, [values, local]);

  const setValue = (key: string, value: string) => setValues((prev) => ({ ...prev, [key]: value }));

  const saveLocal = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${SETTINGS_BASE}/api/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      const data = (await r.json()) as { ok?: boolean; error?: string; status?: Record<string, KeyStatus> };
      if (!r.ok || !data.ok) throw new Error(data.error || `HTTP ${r.status}`);
      setStatus(data.status || {});
      flash("ok", "已写入项目根 .env，本地流水线下次运行即生效（CI 需另行同步，见下方按钮）");
    } catch (err) {
      flash("err", `保存失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const testLLM = async () => {
    const apiKey = (values.DEEPSEEK_API_KEY || "").trim();
    if (!apiKey) {
      flash("err", "请先填写 LLM API Key 再测试");
      return;
    }
    setTesting(true);
    setMsg(null);
    try {
      const r = await fetch("/api/settings/test-llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          apiKey,
          baseUrl: (values.LLM_API_BASE || "").trim(),
          model: (values.LLM_MODEL || "").trim(),
        }),
      });
      const data = (await r.json()) as { ok?: boolean; latencyMs?: number; error?: string };
      if (data.ok) flash("ok", `连接成功（${data.latencyMs ?? "-"} ms）`);
      else flash("err", `连接失败：${data.error || "未知错误"}`);
    } catch (err) {
      flash("err", `测试请求失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setTesting(false);
    }
  };

  const ghCommands = useCallback(() => {
    const lines: string[] = ["# AI HOT · GitHub Actions Secrets/Variables 同步（在仓库目录执行）"];
    for (const k of GH_SECRET_KEYS) {
      const v = (values[k] || "").trim();
      const body = interactiveGh || !v ? "" : ` --body "${v}"`;
      lines.push(`gh secret set ${k} --repo ${REPO}${body}`);
    }
    const base = (values.LLM_API_BASE || "").trim();
    if (base) lines.push(`gh variable set LLM_API_BASE --repo ${REPO} --body "${base}"`);
    return lines.join("\n");
  }, [values, interactiveGh]);

  const downloadEnv = () => {
    const blob = new Blob([buildEnvContent(values)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "aihot.env";
    a.click();
    URL.revokeObjectURL(url);
  };

  const statusText = (f: FieldDef): string => {
    const s = status[f.key];
    if (!s?.set) return "未设置";
    return f.secret ? `已设置（…${s.tail ?? ""}）` : `已设置：${s.value ?? ""}`;
  };

  const inputCls =
    "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-mut-2 focus:border-brand focus:outline-none";
  const primaryCls =
    "rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50";
  const secondaryCls =
    "rounded-lg border border-line bg-surface px-4 py-2 text-sm font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <div className="mx-auto max-w-[680px]">
      <header className="mb-6">
        <h1 className="text-xl font-extrabold text-ink">设置</h1>
        <p className="mt-1 text-sm text-mut-2">
          API Key 配置入口：保存到项目根 <code className="rounded bg-surface-2 px-1 py-0.5 text-xs">.env</code>
          ，本地流水线（打标签 / 正文加工 / Manus 采集）免手动 export 即生效。
        </p>
      </header>

      {!local && (
        <div className="mb-5 rounded-xl border border-amber-300/60 bg-amber-50 p-4 text-sm text-amber-800">
          当前页面运行在非本机环境（{typeof window !== "undefined" ? window.location.hostname : "?"}
          ）。设置页只能在本机（localhost）使用：密钥保存在本机浏览器与本地 .env，公开访问无法读写你的文件。
        </div>
      )}

      {/* 服务状态 */}
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-4">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
            online === null
              ? "bg-surface-2 text-mut-2"
              : online
                ? "bg-emerald-50 text-emerald-700"
                : "bg-red-50 text-red-600"
          }`}
        >
          <span
            className={`size-1.5 rounded-full ${online === null ? "bg-mut-2" : online ? "bg-emerald-500" : "bg-red-500"}`}
          />
          {online === null ? "检测中…" : online ? "本地设置服务在线" : "本地设置服务离线"}
        </span>
        {online === false && (
          <code className="text-xs text-mut-2">cd 项目目录（aihot-site）; node scripts/settings-server.mjs</code>
        )}
        <button
          type="button"
          className={secondaryCls + " !px-3 !py-1.5 text-xs"}
          onClick={() => {
            setOnline(null);
            probe();
          }}
        >
          重新检测
        </button>
      </div>

      {msg && (
        <div
          className={`mb-5 rounded-xl border p-3 text-sm ${
            msg.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : msg.kind === "err"
                ? "border-red-200 bg-red-50 text-red-700"
                : "border-line bg-surface-2 text-mut"
          }`}
        >
          {msg.text}
        </div>
      )}

      {/* 表单 */}
      <div className="mb-6 space-y-5 rounded-xl border border-line bg-surface p-5">
        {FIELDS.map((f) => (
          <div key={f.key}>
            <label htmlFor={`field-${f.key}`} className="mb-1 block text-sm font-semibold text-ink">
              {f.label}
            </label>
            {f.type === "select" ? (
              <select
                id={`field-${f.key}`}
                className={inputCls}
                value={values[f.key] || ""}
                disabled={!local}
                onChange={(e) => setValue(f.key, e.target.value)}
              >
                <option value="">（留空 = 默认）</option>
                {(f.options || []).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            ) : (
              <input
                id={`field-${f.key}`}
                type={f.type}
                className={inputCls}
                placeholder={f.placeholder}
                value={values[f.key] || ""}
                disabled={!local}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => setValue(f.key, e.target.value)}
              />
            )}
            <p className="mt-1 text-xs text-mut-2">
              {statusText(f)}
              {f.desc ? ` · ${f.desc}` : ""}
            </p>
          </div>
        ))}
      </div>

      {/* 操作区 */}
      <div className="mb-8 flex flex-wrap items-center gap-3">
        <button type="button" className={primaryCls} disabled={!local || !online || saving} onClick={saveLocal}>
          {saving ? "保存中…" : "保存到本地 .env"}
        </button>
        <button type="button" className={secondaryCls} disabled={!local || testing} onClick={testLLM}>
          {testing ? "测试中…" : "测试 LLM 连接"}
        </button>
        {online === false && (
          <>
            <button type="button" className={secondaryCls} onClick={downloadEnv}>下载 .env 文件</button>
            <button
              type="button"
              className={secondaryCls}
              onClick={() => {
                void copyText(buildEnvContent(values)).then(
                  () => flash("ok", ".env 内容已复制，请粘贴保存为项目根 .env"),
                  () => flash("err", "复制失败，请手动选择复制"),
                );
              }}
            >
              复制 .env 内容
            </button>
          </>
        )}
        <button
          type="button"
          className={secondaryCls}
          onClick={() => {
            setValues({});
            flash("info", "已清空表单与浏览器记忆（.env 中的已存值不受影响）");
          }}
        >
          清空表单
        </button>
      </div>

      {/* GitHub 同步 */}
      <section className="mb-8 rounded-xl border border-line bg-surface p-5">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-bold text-ink">同步到 GitHub Actions（CI）</h2>
          <label className="flex cursor-pointer items-center gap-2 text-xs text-mut-2">
            <input
              type="checkbox"
              checked={interactiveGh}
              onChange={(e) => setInteractiveGh(e.target.checked)}
              className="accent-brand"
            />
            交互式输入（命令不带明文，避免留在终端历史）
          </label>
        </div>
        <p className="mb-3 text-xs text-mut-2">
          复制后在仓库目录执行一次即可；密钥写入 GitHub Secrets / Variables，CI 定时任务自动使用。
          {!interactiveGh && " 注意：--body 中的密钥会留在终端历史中，请按需清理。"}
        </p>
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-page p-3 font-mono text-xs leading-relaxed text-ink-2">
          {ghCommands()}
        </pre>
        <button
          type="button"
          className={secondaryCls + " mt-3"}
          onClick={() => {
            void copyText(ghCommands()).then(
              () => flash("ok", "GitHub 同步命令已复制"),
              () => flash("err", "复制失败，请手动选择复制"),
            );
          }}
        >
          复制 GitHub 同步命令
        </button>
      </section>

      {/* 说明 */}
      <section className="rounded-xl border border-line bg-surface p-5 text-sm">
        <h2 className="mb-2 text-sm font-bold text-ink">环境变量说明</h2>
        <table className="w-full text-left text-xs text-mut">
          <thead>
            <tr className="border-b border-line text-mut-2">
              <th className="py-1.5 pr-3 font-semibold">变量</th>
              <th className="py-1.5 pr-3 font-semibold">用途</th>
              <th className="py-1.5 font-semibold">消费方</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-line-2">
              <td className="py-1.5 pr-3 font-mono">MANUS_API_KEY</td>
              <td className="py-1.5 pr-3">公众号文章采集</td>
              <td className="py-1.5">fetch-manus.yml · runner.py</td>
            </tr>
            <tr className="border-b border-line-2">
              <td className="py-1.5 pr-3 font-mono">DEEPSEEK_API_KEY</td>
              <td className="py-1.5 pr-3">AI 打标签 + 正文加工</td>
              <td className="py-1.5">build_snapshot.py · enrich_news.py</td>
            </tr>
            <tr className="border-b border-line-2">
              <td className="py-1.5 pr-3 font-mono">TAVILY_API_KEY</td>
              <td className="py-1.5 pr-3">融资表格缺失字段搜索补全（可选）</td>
              <td className="py-1.5">funding_table.py</td>
            </tr>
            <tr className="border-b border-line-2">
              <td className="py-1.5 pr-3 font-mono">LLM_API_BASE</td>
              <td className="py-1.5 pr-3">LLM 服务地址（可换服务商）</td>
              <td className="py-1.5">llm_common.py（CI 用 variable）</td>
            </tr>
            <tr className="border-b border-line-2">
              <td className="py-1.5 pr-3 font-mono">LLM_MODEL</td>
              <td className="py-1.5 pr-3">模型名覆盖 taxonomy 默认</td>
              <td className="py-1.5">llm_common.py（换模型自动失效缓存）</td>
            </tr>
            <tr>
              <td className="py-1.5 pr-3 font-mono">MANUS_AGENT_PROFILE</td>
              <td className="py-1.5 pr-3">Manus 智能体档位</td>
              <td className="py-1.5">runner.py · content_phase.py</td>
            </tr>
          </tbody>
        </table>
        <p className="mt-3 text-xs leading-relaxed text-mut-2">
          密钥只写入本机 .env（已被 .gitignore 忽略）与 GitHub Secrets，不会出现在任何页面响应中；
          保存后本地流水线（python scripts/build_snapshot.py 等）无需重启即可读取。
        </p>
      </section>
    </div>
  );
}
