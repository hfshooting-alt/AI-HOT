"use client";

import { useEffect, useState } from "react";
import type { DailyReportItem, HistoryEntry } from "../../_lib/domain/types";
import { loadDailyReport } from "../../_lib/data/api";
import { fmtCnDate, fmtWeekday } from "../../_lib/display/format";
import { ArrowRightIcon } from "../shared/icons";

/** 日报条目轻量卡片：来源 chip + 标题（外链）+ 摘要（上游日报条目无 id/score/分类标签） */
function ReportItemCard({ item }: { item: DailyReportItem }) {
  const url = item.links?.original || item.links?.aihot;
  return (
    <article className="ah-card ah-card-hover p-5">
      <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-[12px] text-mut-2">日报条目</span>
        {item.source?.name && (
          <span
            className="max-w-[260px] truncate rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[11.5px] text-mut"
            title={item.source.name}
          >
            {item.source.name}
          </span>
        )}
      </div>
      <h3 className="text-[16px] leading-snug font-bold text-ink">
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-brand hover:underline decoration-brand/40 underline-offset-4"
          >
            {item.title}
          </a>
        ) : (
          item.title
        )}
      </h3>
      {item.summary && (
        <p className="mt-2 line-clamp-3 text-[13px] leading-relaxed text-mut">{item.summary}</p>
      )}
    </article>
  );
}

/** 日报详情：VOL 期刊头 + 导语/快讯 + 版块分组条目卡片 */
export function DailyDetail({ entry }: { entry: HistoryEntry }) {
  const [report, setReport] = useState<Awaited<ReturnType<typeof loadDailyReport>>>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!entry.date) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      const data = await loadDailyReport(entry.date);
      if (!cancelled) {
        setReport(data);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [entry.date]);

  const dateIso = `${entry.date}T00:00:00Z`;
  const total = report
    ? report.sections.reduce((n, s) => n + s.items.length, 0) + (report.flashes?.length || 0)
    : entry.total;

  return (
    <div>
      {/* 期刊头 + 完整归档次要入口 */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[12px] tracking-[0.2em] text-mut uppercase">
            VOL.{entry.date.replaceAll("-", ".")} · {total} STORIES · AI HOT DAILY
          </div>
          <h2 className="mt-2 text-[30px] font-extrabold">
            <span className="text-brand">AI HOT</span> <span className="text-ink">日报</span>
          </h2>
          <p className="mt-1 text-[12.5px] text-mut">
            {fmtCnDate(dateIso)} {fmtWeekday(dateIso)} · DAILY · 每日上午十时
            {entry.finalized ? " · 已定稿" : " · 更新中"}
          </p>
        </div>
        <a
          href={entry.url}
          className="mt-1 inline-flex items-center gap-1 text-[12.5px] text-mut transition-colors hover:text-brand"
        >
          完整归档 <ArrowRightIcon />
        </a>
      </div>

      {/* 正文：加载骨架 / 数据兜底 / 版块分组渲染 */}
      <div className="mt-6">
        {loading ? (
          <div className="flex flex-col gap-3.5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="ah-card h-[120px] animate-pulse bg-surface-2" />
            ))}
          </div>
        ) : report && report.sections.length ? (
          <div className="flex flex-col gap-7">
            {report.lead && (report.lead.title || report.lead.summary) && (
              <div className="ah-card p-5">
                <h3 className="text-[14px] font-bold text-ink">今日导语</h3>
                {report.lead.title && (
                  <p className="mt-2 text-[14.5px] font-semibold text-ink">{report.lead.title}</p>
                )}
                {report.lead.summary && (
                  <p className="mt-1.5 text-[13px] leading-relaxed text-mut">{report.lead.summary}</p>
                )}
              </div>
            )}
            {report.flashes && report.flashes.length > 0 && (
              <section>
                <SectionHeader label="快讯" count={report.flashes.length} />
                <div className="flex flex-col gap-3.5">
                  {report.flashes.map((f, i) => (
                    <ReportItemCard key={`${f.title}-${i}`} item={f} />
                  ))}
                </div>
              </section>
            )}
            {report.sections.map((sec) => (
              <section key={sec.label}>
                <SectionHeader label={sec.label} count={sec.items.length} />
                {sec.items.length ? (
                  <div className="flex flex-col gap-3.5">
                    {sec.items.map((it, i) => (
                      <ReportItemCard key={`${it.title}-${i}`} item={it} />
                    ))}
                  </div>
                ) : (
                  <p className="ah-card p-5 text-center text-[12.5px] text-mut">本版块当日无内容</p>
                )}
              </section>
            ))}
          </div>
        ) : (
          /* 上游日报数据不可用时兜底：当日头条 + 完整归档入口 */
          <div className="ah-card p-6 text-center">
            <p className="text-[13px] text-mut">
              当日日报正文暂不可用{entry.title ? `，头条：${entry.title}` : ""}。
            </p>
            <a
              href={entry.url}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-brand px-4 py-2 text-[13px] font-semibold text-brand transition-colors hover:bg-brand hover:text-white"
            >
              查看当日完整归档 <ArrowRightIcon />
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

/** 版块分组头：版块名 + 条数 + 分隔线（对齐 DateGroup 组头视觉） */
function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="mb-3 flex w-full items-center gap-2">
      <span className="text-[15px] font-bold text-ink">{label}</span>
      <span className="text-[12.5px] text-mut">· {count} 条</span>
      <span className="ml-2 h-px flex-1 bg-line" aria-hidden />
    </div>
  );
}
