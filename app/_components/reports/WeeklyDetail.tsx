"use client";

import { useEffect, useMemo, useState } from "react";
import type { NewsItem, WeeklyNavEntry } from "../../_lib/domain/types";
import { loadWeeklyJournal } from "../../_lib/data/api";
import { bjDayKey, fmtMonthDay, fmtWeekday } from "../../_lib/display/format";
import { ArrowRightIcon } from "../shared/icons";
import { ArticleCard } from "../news/ArticleCard";
import { DateGroup } from "../news/DateGroup";

/** 周报详情：VOL 期刊头 + 按日期分组完整条目卡片 */
export function WeeklyDetail({ entry }: { entry: WeeklyNavEntry }) {
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
