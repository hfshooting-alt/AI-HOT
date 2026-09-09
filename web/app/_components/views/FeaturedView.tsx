// 精选视图：按时间戳倒序的精选新闻流 + 新 6 类 Tab + 维度标签筛选 + 搜索 + 当前热点入口
"use client";

import { useEffect, useMemo, useState } from "react";
import type { CompanyOverview, FundingTable, HotTopic, NewsItem } from "../../_lib/domain/types";
import { loadCompanyOverview, loadFeatured, loadFundingTable, loadHot, loadSnapshot, mergePools, poolFromSnapshot } from "../../_lib/data/api";
import {
  bjDayKey,
  fmtFullDay,
  fmtMonthDay,
  fmtWeekday,
  heatOf,
} from "../../_lib/display/format";
import { categoryDisplay, categoryOf, matchDims, TAXONOMY_CATEGORIES } from "../../_lib/domain/taxonomy";
import { FUNDING_DIMENSIONS, FUNDING_DIM_IDS } from "../../_lib/domain/fundingTaxonomy";
import { useApp } from "../providers/AppDataProvider";
import { ArticleCard } from "../news/ArticleCard";
import type { TabOption } from "../news/CategoryTabs";
import { ContentNavigator } from "../news/ContentNavigator";
import { DateGroup } from "../news/DateGroup";
import { FundingTableView } from "../funding/FundingTableView";
import { CompanyOverviewTable } from "../company/CompanyOverviewTable";
import { ArrowRightIcon } from "../shared/icons";
import { SearchToolbar, type SourceFilter } from "../news/SearchToolbar";
import { TagFilterBar, type DimSelection } from "../news/TagFilterBar";
import { matchItem, sourceKindOf } from "../../_lib/display/source";

/** 跨导航切换保留筛选状态（模块级缓存） */
const persisted: { cat: string; q: string; src: SourceFilter; dimSel: DimSelection } = {
  cat: "all",
  q: "",
  src: "all",
  dimSel: {},
};

export function FeaturedView() {
  const { setView } = useApp();
  const [pool, setPool] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [liveOk, setLiveOk] = useState(true);
  const [hotTop, setHotTop] = useState<HotTopic[]>([]);
  const [cat, setCat] = useState(persisted.cat);
  const [q, setQ] = useState(persisted.q);
  const [src, setSrc] = useState<SourceFilter>(persisted.src);
  const [dimSel, setDimSel] = useState<DimSelection>(persisted.dimSel);
  const [today, setToday] = useState("");
  /** 融资表格（构建产物）：null 且 ready 时回退卡片流 */
  const [fundingTable, setFundingTable] = useState<FundingTable | null>(null);
  const [fundingReady, setFundingReady] = useState(false);
  const [companyOverview, setCompanyOverview] = useState<CompanyOverview | null>(null);
  const [overviewReady, setOverviewReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setToday(fmtFullDay(new Date().toISOString()));
      const snap = await loadSnapshot();
      const base = snap ? poolFromSnapshot(snap) : [];
      if (cancelled) return;
      if (base.length) {
        setPool(base);
        setLoading(false);
      }
      try {
        const live = await loadFeatured();
        if (cancelled) return;
        if (live.length) setPool(base.length ? mergePools(base, live) : live);
        setLiveOk(true);
      } catch {
        setLiveOk(false);
      }
      setLoading(false);
    })();
    loadHot().then((r) => {
      if (!cancelled && r) setHotTop(r.items.slice(0, 3));
    });
    loadFundingTable().then((t) => {
      if (!cancelled) {
        setFundingTable(t);
        setFundingReady(true);
      }
    });
    loadCompanyOverview().then((data) => {
      if (!cancelled) {
        setCompanyOverview(data);
        setOverviewReady(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /** 分类 Tab：全部 + 新 6 类（固定顺序，计数基于 categoryOf，0 也显示以保证类别齐全） */
  const tabOptions = useMemo<TabOption[]>(() => {
    const counter = new Map<string, number>();
    for (const it of pool) {
      const key = categoryOf(it);
      counter.set(key, (counter.get(key) || 0) + 1);
    }
    const opts: TabOption[] = [{ key: "all", label: "全部", count: pool.length }];
    for (const c of TAXONOMY_CATEGORIES) {
      opts.push({ key: c.id, label: c.label, count: counter.get(c.id) || 0 });
    }
    return opts;
  }, [pool]);

  /** 融资动态表格模式：分类声明 table 且构建产物有公司行（缺失/空表回退卡片流） */
  const wantTable = categoryDisplay(cat) === "table";
  const tableMode = wantTable && (fundingTable?.companies?.length ?? 0) > 0;
  const tablePending = wantTable && !fundingReady;
  const overviewMode = cat === "overview";
  const overviewPending = cat === "overview" && !overviewReady;

  /** 当前类别的维度标签筛选（「全部」或无维度类别不显示；融资表格使用专属维度） */
  const activeDims = useMemo(() => {
    if (cat === "all") return [];
    if (cat === "overview") return ["industry", "region"];
    if (tableMode) return FUNDING_DIM_IDS;
    return TAXONOMY_CATEGORIES.find((c) => c.id === cat)?.dims ?? [];
  }, [cat, tableMode]);

  /** 每日最多 15 条精选 */
  const MAX_FEATURED_PER_DAY = 15;

  /** 过滤（类别 → 维度标签 → 来源 → 搜索）+ 按北京日期分组（时间戳倒序，每日上限 15 条） */
  const groups = useMemo(() => {
    const filtered = pool.filter((it) => {
      if (cat !== "all" && categoryOf(it) !== cat) return false;
      if (!matchDims(it, dimSel)) return false;
      if (src !== "all" && sourceKindOf(it) !== src) return false;
      if (!matchItem(it, q)) return false;
      return true;
    });
    const map = new Map<string, NewsItem[]>();
    for (const it of filtered) {
      const key = bjDayKey(it.publishedAt) || "unknown";
      const arr = map.get(key);
      if (arr) {
        if (arr.length < MAX_FEATURED_PER_DAY) arr.push(it);
      } else {
        map.set(key, [it]);
      }
    }
    return [...map.entries()];
  }, [pool, cat, q, src, dimSel]);

  const totalShown = groups.reduce((n, [, items]) => n + items.length, 0);

  return (
    <div>
      {/* 页头：标题 + 搜索 */}
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-extrabold text-ink">精选</h1>
          <p className="mt-1 text-[13px] text-mut">{today} · AI 精选今日重点（每天最多 15 条）</p>
        </div>
        <div className="flex w-full max-w-[340px] items-center gap-2 sm:w-auto">
          <SearchToolbar
            q={q}
            placeholder={overviewMode ? "搜索公司、产品、业务、团队…" : tableMode ? "搜索融资公司与业务…" : undefined}
            onQChange={(v) => {
              setQ(v);
              persisted.q = v;
            }}
            src={src}
            onSrcChange={(v) => {
              setSrc(v);
              persisted.src = v;
            }}
            showSourceFilter={!tableMode && !overviewMode}
          />
        </div>
      </header>

      {/* 当前热点（前 3 条，入口跳转热点榜） */}
      {hotTop.length > 0 && (
        <div className="ah-card mb-6 p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[15px] font-bold text-ink">当前热点</h2>
            <button
              type="button"
              onClick={() => setView("hot")}
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-brand hover:text-brand-strong"
            >
              完整榜单 <ArrowRightIcon />
            </button>
          </div>
          <ol className="flex flex-col divide-y divide-line-2">
            {hotTop.map((t) => (
              <li key={t.id} className="flex items-center gap-3 py-2.5">
                <span className="w-5 text-center text-[15px] font-extrabold text-heat-red">{t.rank}</span>
                <a
                  href={t.links.original}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink-2 hover:text-brand"
                  title={t.title}
                >
                  {t.title}
                </a>
                <span className="text-[12px] font-bold whitespace-nowrap text-ink">{heatOf(t)} 热度</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <ContentNavigator
        options={tabOptions}
        active={cat}
        overview={companyOverview}
        onChange={(key) => {
          setCat(key);
          persisted.cat = key;
          setDimSel({});
          persisted.dimSel = {};
        }}
      />

      {/* 当前内容的维度标签筛选 */}
      {activeDims.length > 0 && (
        <div className="ah-card mb-6 px-4 py-3.5 sm:px-5">
          <TagFilterBar
            dims={activeDims}
            selection={dimSel}
            onChange={(next) => {
              setDimSel(next);
              persisted.dimSel = next;
            }}
            dimsDef={tableMode ? FUNDING_DIMENSIONS : undefined}
          />
        </div>
      )}

      {/* 内容区：融资动态用公司表格；其余类别卡片流（表格产物缺失时回退卡片） */}
      {loading || tablePending || overviewPending ? (
        <div className="flex flex-col gap-3.5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="ah-card h-[120px] animate-pulse bg-surface-2" />
          ))}
        </div>
      ) : overviewMode && companyOverview ? (
        <CompanyOverviewTable overview={companyOverview} dimSel={dimSel} q={q} />
      ) : overviewMode ? (
        <p className="ah-card p-8 text-center text-[13px] text-mut">
          公司与产品库尚未生成。配置模型后运行 overview 阶段即可产生首版数据。
        </p>
      ) : tableMode && fundingTable ? (
        <FundingTableView table={fundingTable} dimSel={dimSel} q={q} />
      ) : totalShown === 0 ? (
        <p className="ah-card p-8 text-center text-[13px] text-mut">
          无匹配内容{!liveOk && "（实时接口不可用，且快照为空）"}，试试切换分类、来源筛选或清空搜索词。
        </p>
      ) : (
        groups.map(([dayKey, items]) => (
          <DateGroup
            key={dayKey}
            monthDay={dayKey === "unknown" ? "时间未知" : fmtMonthDay(items[0].publishedAt)}
            weekday={dayKey === "unknown" ? "" : fmtWeekday(items[0].publishedAt)}
            count={items.length}
          >
            {items.map((it) => (
              <ArticleCard key={it.id} item={it} />
            ))}
          </DateGroup>
        ))
      )}

      {!tableMode && !overviewMode && (
        <footer className="mt-10 border-t border-line pt-5 text-center text-[12px] text-mut-2">
          共 {totalShown} 条精选 · 数据来源：AI HOT 开放 API · 时间为北京时间 · 摘要由 AI 生成，点击标题核对原文
        </footer>
      )}
    </div>
  );
}
