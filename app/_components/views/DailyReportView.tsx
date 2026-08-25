// AI 日报视图：仅日报 / 周报两种粒度（无月报）
// 日报/周报正文在日期栏右侧直接渲染（统一卡片风格），旧版归档页保留为次要入口
"use client";

import { useEffect, useMemo, useState } from "react";
import type { DailyReportItem, HistoryEntry, NewsItem, Snapshot, WeeklyNavEntry } from "../../_lib/types";
import { loadDailyReport, loadSnapshot, loadWeeklyJournal } from "../../_lib/api";
import { bjDayKey, fmtCnDate, fmtMonthDay, fmtWeekday } from "../../_lib/format";
import { ArrowRightIcon } from "../icons";
import { ArticleCard } from "../ArticleCard";
import { DateGroup } from "../DateGroup";

type Tab = "daily" | "weekly";

export function DailyReportView() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [tab, setTab] = useState<Tab>("daily");
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [selectedWeek, setSelectedWeek] = useState<string>(""); // weekly url 作为键

  useEffect(() => {
    loadSnapshot().then((s) => {
      setSnap(s);
      if (s?.history?.length) setSelectedDate(s.history[0].date);
      if (s?.weeklyNav?.length) setSelectedWeek(s.weeklyNav[0].url);
    });
  }, []);

  /** 日报按月份分组（新到旧） */
  const dailyMonths = useMemo(() => {
    const map = new Map<string, HistoryEntry[]>();
    for (const h of snap?.history || []) {
      const key = h.date.slice(0, 7); // YYYY-MM
      const arr = map.get(key);
      if (arr) arr.push(h);
      else map.set(key, [h]);
    }
    return [...map.entries()];
  }, [snap]);

  /** 周报按月份分组：从 url 中解析周起始日期 */
  const weeklyMonths = useMemo(() => {
    const map = new Map<string, (WeeklyNavEntry & { weekStart: string })[]>();
    for (const w of snap?.weeklyNav || []) {
      const m = w.url.match(/weekly\/(\d{4}-\d{2}-\d{2})/);
      const weekStart = m ? m[1] : "";
      const key = weekStart.slice(0, 7) || "unknown";
      const arr = map.get(key);
      if (arr) arr.push({ ...w, weekStart });
      else map.set(key, [{ ...w, weekStart }]);
    }
    return [...map.entries()];
  }, [snap]);

  const currentDaily = (snap?.history || []).find((h) => h.date === selectedDate) || null;
  const currentWeekly = (snap?.weeklyNav || []).find((w) => w.url === selectedWeek) || null;

  const monthLabel = (key: string) => {
    if (key === "unknown") return "未知月份";
    const [y, m] = key.split("-");
    return `${y} 年 ${Number(m)} 月`;
  };

  const tabBtn = (t: Tab, label: string) => (
    <button
      key={t}
      type="button"
      onClick={() => setTab(t)}
      className={`rounded-lg px-5 py-1.5 text-[13px] font-semibold transition-colors ${
        tab === t ? "bg-surface-2 text-ink shadow-sm ring-1 ring-line" : "text-mut hover:text-ink"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div>
      {/* 页头 + 粒度切换（仅日报 / 周报，无月报） */}
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-extrabold text-ink">AI 日报</h1>
          <p className="mt-1 text-[13px] text-mut">每日晨报与每周综述 · 按月份归档组织</p>
        </div>
        <div className="flex gap-1 rounded-xl border border-line bg-surface p-1">
          {tabBtn("daily", "日报")}
          {tabBtn("weekly", "周报")}
        </div>
      </header>

      {!snap ? (
        <div className="ah-card h-[220px] animate-pulse bg-surface-2" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
          {/* 左列：月份归档索引 */}
          <aside className="ah-card ah-scroll h-fit max-h-[calc(100vh-180px)] overflow-y-auto p-4 lg:sticky lg:top-6">
            {tab === "daily" ? (
              dailyMonths.length === 0 ? (
                <p className="p-2 text-[12px] text-mut">归档积累中…</p>
              ) : (
                dailyMonths.map(([key, days]) => (
                  <div key={key} className="mb-4">
                    <div className="mb-2 flex items-baseline justify-between px-1">
                      <span className="text-[13px] font-bold text-ink">{monthLabel(key)}</span>
                      <span className="text-[11.5px] text-mut-2">{days.length}</span>
                    </div>
                    <ul className="flex flex-col gap-0.5">
                      {days.map((h) => (
                        <li key={h.date}>
                          <button
                            type="button"
                            onClick={() => setSelectedDate(h.date)}
                            className={`flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
                              selectedDate === h.date
                                ? "bg-brand-soft font-semibold text-brand-strong"
                                : "text-ink-2 hover:bg-surface-2"
                            }`}
                          >
                            <span>{h.label.replace(/\s.*$/, "")}</span>
                            <span className="text-[11px] text-mut-2">{h.total}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              )
            ) : weeklyMonths.length === 0 ? (
              <p className="p-2 text-[12px] text-mut">首个完结自然周后产出…</p>
            ) : (
              weeklyMonths.map(([key, weeks]) => (
                <div key={key} className="mb-4">
                  <div className="mb-2 px-1 text-[13px] font-bold text-ink">{monthLabel(key)}</div>
                  <ul className="flex flex-col gap-0.5">
                    {weeks.map((w) => (
                      <li key={w.url}>
                        <button
                          type="button"
                          onClick={() => setSelectedWeek(w.url)}
                          className={`w-full rounded-md px-2.5 py-2 text-left transition-colors ${
                            selectedWeek === w.url ? "bg-brand-soft" : "hover:bg-surface-2"
                          }`}
                        >
                          <span className={`block text-[12.5px] ${selectedWeek === w.url ? "font-semibold text-brand-strong" : "text-ink-2"}`}>
                            {w.label}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-mut-2">
                            {w.range} · {w.total} 条
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </aside>

          {/* 右列：日报/周报正文（统一卡片风格，完整归档为次要入口） */}
          <main>
            {tab === "daily" ? (
              currentDaily ? (
                <DailyDetail entry={currentDaily} />
              ) : (
                <EmptyPanel text="暂无日报归档" />
              )
            ) : currentWeekly ? (
              <WeeklyDetail entry={currentWeekly} />
            ) : (
              <EmptyPanel text="暂无周报归档" />
            )}
          </main>
        </div>
      )}
    </div>
  );
}

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
function DailyDetail({ entry }: { entry: HistoryEntry }) {
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
            {fmtCnDate(dateIso)} {fmtWeekday(dateIso)} · DAILY · 每早八时
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

/** 周报详情：VOL 期刊头 + 按日期分组完整条目卡片 */
function WeeklyDetail({ entry }: { entry: WeeklyNavEntry }) {
  const m = entry.url.match(/weekly\/(\d{4})-(\d{2})-(\d{2})/);
  const year = m ? m[1] : "";
  const weekStart = m ? `${m[1]}-${m[2]}-${m[3]}` : "";
  const [journal, setJournal] = useState<Awaited<ReturnType<typeof loadWeeklyJournal>>>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!weekStart) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      const data = await loadWeeklyJournal(weekStart);
      if (!cancelled) {
        setJournal(data);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [weekStart]);

  /** 按北京日期分组（时间戳倒序） */
  const groups = useMemo(() => {
    const map = new Map<string, NewsItem[]>();
    for (const it of journal?.items || []) {
      const key = bjDayKey(it.publishedAt) || "unknown";
      const arr = map.get(key);
      if (arr) arr.push(it);
      else map.set(key, [it]);
    }
    return [...map.entries()];
  }, [journal]);

  return (
    <div>
      {/* 期刊头 + 完整归档次要入口 */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[12px] tracking-[0.2em] text-mut uppercase">
            VOL.{year} · {entry.label} · WEEKLY
          </div>
          <h2 className="mt-2 text-[30px] font-extrabold text-ink">{entry.label}</h2>
          <p className="mt-1 text-[12.5px] text-mut">
            {entry.range} · WEEKLY · 编辑系统自动综合 · {journal?.items.length ?? entry.total} 条
          </p>
        </div>
        <a
          href={entry.url}
          className="mt-1 inline-flex items-center gap-1 text-[12.5px] text-mut transition-colors hover:text-brand"
        >
          完整归档 <ArrowRightIcon />
        </a>
      </div>

      <div className="mt-6">
        {loading ? (
          <div className="flex flex-col gap-3.5">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="ah-card h-[110px] animate-pulse bg-surface-2" />
            ))}
          </div>
        ) : journal && journal.items.length ? (
          groups.map(([dayKey, list]) => (
            <DateGroup
              key={dayKey}
              monthDay={dayKey === "unknown" ? "时间未知" : fmtMonthDay(list[0].publishedAt)}
              weekday={dayKey === "unknown" ? "" : fmtWeekday(list[0].publishedAt)}
              count={list.length}
            >
              {list.map((it) => (
                <ArticleCard key={it.id} item={it} />
              ))}
            </DateGroup>
          ))
        ) : (
          /* 周报数据不可用时兜底 */
          <div className="ah-card p-6 text-center">
            <p className="text-[13px] text-mut">本期周期刊正文暂不可用。</p>
            <a
              href={entry.url}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-brand px-4 py-2 text-[13px] font-semibold text-brand transition-colors hover:bg-brand hover:text-white"
            >
              查看本期周期刊 <ArrowRightIcon />
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

function EmptyPanel({ text }: { text: string }) {
  return <div className="ah-card p-10 text-center text-[13px] text-mut">{text}</div>;
}
