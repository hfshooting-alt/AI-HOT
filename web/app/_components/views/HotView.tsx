// 热点榜视图：调用 AI HOT API（/api/v1/hot-topics 代理）按热度排序展示
"use client";

import { useEffect, useState } from "react";
import type { HotTopic } from "../../_lib/domain/types";
import { loadHot } from "../../_lib/data/api";
import { fmtRelative, heatOf, seededSeries } from "../../_lib/display/format";

/** 热度标签：爆（短时密集）/ 新（首报 6 小时内）/ 发酵中（信源仍在增加） */
function heatTag(t: HotTopic): string | null {
  const ageMs = Date.now() - new Date(t.latestAt).getTime();
  if (t.signalCount >= 3) return "爆";
  if (ageMs < 6 * 3600 * 1000) return "新";
  if (t.sourceCount >= 3) return "发酵中";
  return null;
}

/** 装饰性趋势线（基于事件 id 的稳定伪随机，终点圆点） */
function Sparkline({ seed, rising }: { seed: string; rising: boolean }) {
  const pts = seededSeries(seed, 7, 8, 26);
  if (rising) pts.sort((a, b) => a - b);
  const path = pts.map((y, i) => `${4 + i * 14},${34 - y}`).join(" ");
  const [lx, ly] = [4 + 6 * 14, 34 - pts[6]];
  return (
    <svg viewBox="0 0 96 38" className="h-[38px] w-[96px] shrink-0" aria-hidden>
      <polyline points={path} fill="none" stroke="#b9c2cc" strokeWidth="2" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="3.5" fill="#6b7280" />
    </svg>
  );
}

const RANK_COLOR = ["text-heat-red", "text-heat-orange", "text-heat-gold"];

export function HotView() {
  const [topics, setTopics] = useState<HotTopic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openSources, setOpenSources] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadHot().then((r) => {
      if (cancelled) return;
      if (r) {
        setTopics([...r.items].sort((a, b) => heatOf(b) - heatOf(a)).map((t, i) => ({ ...t, rank: i + 1 })));
      } else {
        setError("热点榜接口暂不可用，请稍后再试");
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <header className="mb-7">
        <h1 className="text-[26px] font-extrabold text-ink">AI 热点榜</h1>
        <p className="mt-1 text-[13px] text-mut">过去 48 小时最热的 AI 事件，按精选报道与讨论热度实时排序。</p>
      </header>

      {/* NOW 当前热点 */}
      <div className="mb-4 flex items-center gap-3">
        <span className="rounded-md bg-heat-red px-2 py-0.5 text-[11px] font-extrabold tracking-wider text-white">NOW</span>
        <h2 className="text-[16px] font-bold text-ink">当前热点</h2>
        <span className="text-[12.5px] text-mut">{topics.length} 个事件</span>
      </div>

      {loading ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="ah-card h-[96px] animate-pulse bg-surface-2" />
          ))}
        </div>
      ) : error ? (
        <p className="ah-card p-8 text-center text-[13px] text-mut">{error}</p>
      ) : (
        <ol className="flex flex-col gap-3">
          {topics.map((t) => {
            const tag = heatTag(t);
            const heat = heatOf(t);
            return (
              <li key={t.id} className="ah-card ah-card-hover p-5">
                <div className="flex items-start gap-4">
                  {/* 排名 */}
                  <div className={`w-12 shrink-0 pt-1 text-[22px] leading-none font-extrabold ${RANK_COLOR[t.rank - 1] || "text-mut-2"}`}>
                    #{String(t.rank).padStart(2, "0")}
                  </div>

                  {/* 标题 + 来源 */}
                  <div className="min-w-0 flex-1">
                    <a
                      href={t.links.original}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[15.5px] leading-snug font-bold text-ink hover:text-brand"
                    >
                      {t.title}
                    </a>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px] text-mut">
                      <span className="truncate">{t.source?.name}</span>
                      <span aria-hidden>·</span>
                      <span>{fmtRelative(t.latestAt)}</span>
                      {tag && (
                        <span className="rounded-full bg-[var(--tag-beige-bg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--tag-beige-ink)]">
                          {tag}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* 趋势线 + 热度值 */}
                  <div className="hidden items-center gap-5 sm:flex">
                    <Sparkline seed={t.id} rising={heat >= 40} />
                    <button
                      type="button"
                      onClick={() => setOpenSources(openSources === t.id ? null : t.id)}
                      className="w-16 text-center"
                      title="点击查看信源名单"
                    >
                      <span className="block text-[22px] leading-none font-extrabold text-ink">{heat}</span>
                      <span className="mt-1 block text-[11px] text-mut-2">热度值</span>
                    </button>
                  </div>
                </div>

                {/* 信源名单（点击热度值展开） */}
                {openSources === t.id && (
                  <div className="ah-dashed mt-4 flex flex-wrap gap-2 pt-4">
                    <span className="text-[12px] text-mut">信源名单：</span>
                    {t.sourceNames.map((s) => (
                      <span key={s} className="rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-[11.5px] text-ink-2">
                        {s}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {/* 榜单口径说明 */}
      <p className="mt-6 text-[12px] leading-relaxed text-mut-2">
        榜单热度 = 精选信源权重 + 氛围票权重，并按 24 小时半衰期衰减；同一故事线的关联事件在榜单综合计算。标签含义：
        <b className="text-mut">爆</b> 短时间密集报道、<b className="text-mut">新</b> 首报 6 小时内、
        <b className="text-mut">发酵中</b> 信源仍在增加。点击右侧热度数字可查看信源名单。
      </p>
    </div>
  );
}
