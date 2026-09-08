// AI 日报视图：仅日报 / 周报两种粒度（无月报）
// 日报/周报正文在日期栏右侧直接渲染（统一卡片风格），旧版归档页保留为次要入口
"use client";

import { useEffect, useMemo, useState } from "react";
import type { HistoryEntry, Snapshot, WeeklyNavEntry } from "../../_lib/domain/types";
import { loadSnapshot } from "../../_lib/data/api";
import { DailyDetail } from "../reports/DailyDetail";
import { WeeklyDetail } from "../reports/WeeklyDetail";

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

function EmptyPanel({ text }: { text: string }) {
  return <div className="ah-card p-10 text-center text-[13px] text-mut">{text}</div>;
}
