// 全部文章与 Garena 投资精选共用的新闻流；数据池与筛选状态分别保存。
// 支持：新闻分类 Tab（融资移至公司全景） + 维度标签筛选 + 来源筛选（一手信源/资讯/推文/公众号）+ 按来源/标题/摘要搜索
"use client";

import { useEffect, useMemo, useState } from "react";
import type { NewsItem, NewsPoolMode } from "../../_lib/domain/types";
import { loadSnapshot, poolFromSnapshot, newsPoolError } from "../../_lib/data/api";
import { bjDayKey, fmtMonthDay, fmtWeekday } from "../../_lib/display/format";
import { ARTICLE_STATUS_FILTERS, categoryOf, matchDims, TAXONOMY_CATEGORIES } from "../../_lib/domain/taxonomy";
import { matchItem, sourceKindOf } from "../../_lib/display/source";
import { ArticleCard } from "../news/ArticleCard";
import { CategoryTabs, type TabOption } from "../news/CategoryTabs";
import { DateGroup } from "../news/DateGroup";
import { SearchToolbar, type SourceFilter } from "../news/SearchToolbar";
import { TagFilterBar, type DimSelection } from "../news/TagFilterBar";

/** 跨导航切换保留筛选状态（模块级缓存） */
const persisted: Record<NewsPoolMode, { tag: string; q: string; src: SourceFilter; dimSel: DimSelection }> = {
  all: { tag: "all", q: "", src: "all", dimSel: {} },
  selected: { tag: "all", q: "", src: "all", dimSel: {} },
};

export function AllAIView({ mode = "all" }: { mode?: NewsPoolMode }) {
  const saved = persisted[mode];
  const [items, setItems] = useState<NewsItem[]>([]);
  const [tag, setTag] = useState(saved.tag === "financing" ? "all" : saved.tag);
  const [q, setQ] = useState(saved.q);
  const [src, setSrc] = useState<SourceFilter>(saved.src);
  const [dimSel, setDimSel] = useState<DimSelection>(saved.dimSel);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const snap = await loadSnapshot();
      if (cancelled) return;
      setError(newsPoolError(snap, mode));
      setItems(snap ? poolFromSnapshot(snap, mode) : []);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [mode]);

  /** 分类 Tab：全部 + 新闻分类（固定顺序，计数基于 categoryOf，0 也显示以保证类别齐全） */
  const tabOptions = useMemo<TabOption[]>(() => {
    const counter = new Map<string, number>();
    for (const it of items) {
      const key = categoryOf(it);
      counter.set(key, (counter.get(key) || 0) + 1);
    }
    const opts: TabOption[] = [{ key: "all", label: "全部", count: items.length }];
    for (const c of TAXONOMY_CATEGORIES.filter(c => c.id !== "financing")) {
      opts.push({ key: c.id, label: c.label, count: counter.get(c.id) || 0 });
    }
    for (const status of ARTICLE_STATUS_FILTERS) {
      if (counter.has(status.id)) {
        opts.push({ key: status.id, label: status.label, count: counter.get(status.id) || 0 });
      }
    }
    return opts;
  }, [items]);

  const activeDims = useMemo(() => tag === "all" ? [] : TAXONOMY_CATEGORIES.find(c => c.id === tag)?.dims ?? [], [tag]);

  const filtered = useMemo(
    () =>
      items.filter((it) => {
        if (tag !== "all" && categoryOf(it) !== tag) return false;
        if (!matchDims(it, dimSel)) return false;
        if (src !== "all" && sourceKindOf(it) !== src) return false;
        if (!matchItem(it, q)) return false;
        return true;
      }),
    [items, tag, q, src, dimSel],
  );

  const groups = useMemo(() => {
    const map = new Map<string, NewsItem[]>();
    for (const it of filtered) {
      const key = bjDayKey(it.publishedAt) || "unknown";
      const arr = map.get(key);
      if (arr) arr.push(it);
      else map.set(key, [it]);
    }
    return [...map.entries()];
  }, [filtered]);

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-extrabold text-ink">{mode === "all" ? "全部文章" : "Garena投资精选"}</h1>
          <p className="mt-1 text-[13px] text-mut">{mode === "all" ? "Manus 采集的本轮文章" : "供投资研究参考的 AI 相关资讯"} · 支持来源、分类与搜索筛选</p>
        </div>
        <SearchToolbar
          q={q}
          onQChange={(v) => {
            setQ(v);
            saved.q = v;
          }}
          src={src}
          onSrcChange={(v) => {
            setSrc(v);
            saved.src = v;
          }}
          showSourceFilter={true}
        />
      </header>

      <section className="ah-card mb-6 overflow-hidden" aria-label="资讯分类">
        <div className="border-b border-line bg-gradient-to-r from-brand-softer to-surface px-4 py-3 sm:px-5">
          <p className="text-[11px] font-bold tracking-[0.14em] text-brand">NEWS CATEGORIES</p>
          <h2 className="mt-0.5 text-[15px] font-extrabold text-ink">资讯分类</h2>
        </div>
        <div className="px-4 py-4 sm:px-5">
          <CategoryTabs
            options={tabOptions}
            active={tag}
            onChange={(key) => {
              setTag(key);
              saved.tag = key;
              setDimSel({});
              saved.dimSel = {};
            }}
          />
        </div>
      </section>

      {/* 当前内容的维度标签筛选 */}
      {activeDims.length > 0 && (
        <div className="ah-card mb-6 px-4 py-3.5 sm:px-5">
          <TagFilterBar
            dims={activeDims}
            selection={dimSel}
            onChange={(next) => {
              setDimSel(next);
              saved.dimSel = next;
            }}
          />
        </div>
      )}

      {loading ? (
        <div className="flex flex-col gap-3.5">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="ah-card h-[110px] animate-pulse bg-surface-2" />
          ))}
        </div>
      ) : error ? (
        <p role="alert" className="ah-card p-8 text-center text-[13px] text-mut">{error}</p>
      ) : groups.length === 0 ? (
        <p className="ah-card p-8 text-center text-[13px] text-mut">
          {items.length === 0
            ? mode === "all" ? "本轮暂无已发布的 Manus 文章。" : "本轮暂无 Garena投资精选。"
            : "无匹配内容，试试切换分类、标签、来源筛选或清空搜索词。"}
        </p>
      ) : (
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
      )}
    </div>
  );
}
