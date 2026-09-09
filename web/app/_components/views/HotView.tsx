// 热点榜视图：严格保留 AI HOT /api/v1/hot-topics 返回的排名，不推算内部热度。
"use client";

import { useEffect, useState } from "react";
import type { HotTopic } from "../../_lib/domain/types";
import { loadHot } from "../../_lib/data/api";
import { fmtRelative } from "../../_lib/display/format";

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
        setTopics([...r.items].sort((a, b) => a.rank - b.rank));
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
        <p className="mt-1 text-[13px] text-mut">AIHOT 当前聚合事件，严格保留接口返回排名。</p>
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
                      href={t.links.aihot || t.links.original}
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
                      {t.links.original && t.links.original !== t.links.aihot && (
                        <>
                          <span aria-hidden>·</span>
                          <a
                            href={t.links.original}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-medium text-brand hover:text-brand-strong"
                          >
                            原始报道
                          </a>
                        </>
                      )}
                    </div>
                  </div>

                  {/* 来源数量来自 API；只用于展开来源名单，不作为热度值。 */}
                  <div className="flex items-center">
                    <button
                      type="button"
                      onClick={() => setOpenSources(openSources === t.id ? null : t.id)}
                      className="min-w-20 rounded-lg border border-line px-3 py-2 text-center hover:border-brand/30"
                      title="点击查看信源名单"
                    >
                      <span className="block text-[18px] leading-none font-extrabold text-ink">{t.sourceCount}</span>
                      <span className="mt-1 block text-[11px] text-mut-2">个信源</span>
                    </button>
                  </div>
                </div>

                {/* 信源名单（点击信源数展开） */}
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
        排名由 AIHOT 热点接口直接提供；本站不根据报道数或讨论信号自行计算热度。点击右侧信源数可查看来源名单。
      </p>
    </div>
  );
}
