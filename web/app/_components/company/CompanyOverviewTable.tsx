"use client";

import { useMemo, useState } from "react";
import type { CompanyFieldEvidence, CompanyOverview, CompanyProfile } from "../../_lib/domain/types";
import { TagFilterBar, type DimSelection } from "../news/TagFilterBar";
import { CompanyDetailDrawer } from "./CompanyDetailDrawer";
import { fmtCnDate } from "../../_lib/display/format";

const PAGE_SIZE = 24;
type SortKey = "recent" | "name" | "sources" | "products";

type CompanyColumnKey = keyof CompanyProfile | "industry";

const COLUMNS: { key: CompanyColumnKey; label: string; cellClass: string }[] = [
  { key: "company_name", label: "公司", cellClass: "sticky-col w-[190px]" },
  { key: "updatedAt", label: "更新日期", cellClass: "w-[140px]" },
  { key: "product_names", label: "代表产品", cellClass: "w-[170px]" },
  { key: "founded", label: "成立时间", cellClass: "w-[100px]" },
  { key: "industry", label: "行业", cellClass: "w-[140px]" },
  { key: "country", label: "国家 / 地区", cellClass: "w-[110px]" },
  { key: "business", label: "主营业务", cellClass: "w-[250px]" },
  { key: "team", label: "团队情况", cellClass: "w-[240px]" },
  { key: "investors", label: "历史投资人", cellClass: "w-[190px]" },
  { key: "total_funding", label: "累计融资", cellClass: "w-[130px]" },
  { key: "valuation", label: "最新估值", cellClass: "w-[120px]" },
  { key: "sourceArticles", label: "相关新闻", cellClass: "w-[260px]" },
];

function matches(rec: CompanyProfile, selection: DimSelection, query: string): boolean {
  for (const [label, values] of Object.entries(selection)) {
    const value = label === "国家/地区" ? rec.country || "未披露" : rec.dims?.[label];
    if (values.length && !values.includes(value)) return false;
  }
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [
    rec.company_name,
    ...rec.aliases,
    ...rec.product_names,
    rec.business,
    rec.team,
    rec.investors,
    rec.country,
    rec.dims?.["行业"],
    rec.dims?.["国家/地区"],
  ].some((value) => (value || "").toLowerCase().includes(q));
}

function evidenceFor(rec: CompanyProfile, key: string): CompanyFieldEvidence[] {
  return rec.fieldSources?.[key] || [];
}

function EvidenceValue({ value, evidence, className = "" }: {
  value: string;
  evidence: CompanyFieldEvidence[];
  className?: string;
}) {
  const source = evidence[0];
  const title = evidence.length
    ? `来源（${evidence.length}）：${evidence.map((e) => e.title).join("；")}`
    : undefined;
  return source?.url ? (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className={`decoration-brand/35 underline-offset-2 hover:text-brand hover:underline ${className}`}
      title={title}
    >
      {value}<sup className="ml-1 text-[10px] font-bold text-brand">{evidence.length} 源</sup>
    </a>
  ) : <span className={className} title={title}>{value}</span>;
}

function SourceLinks({ rec, compact = false }: { rec: CompanyProfile; compact?: boolean }) {
  const sources = rec.sourceArticles.slice(0, compact ? 3 : 5);
  if (!sources.length) return <span className="text-mut-2">暂无关联报道</span>;
  return (
    <div className="flex flex-col gap-1.5">
      {sources.map((source, index) => (
        <a
          key={source.id}
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          className="group/source flex min-w-0 items-start gap-1.5 text-ink-2 hover:text-brand"
          title={source.title}
        >
          <span className="mt-0.5 shrink-0 font-mono text-[10px] font-bold text-brand">{String(index + 1).padStart(2, "0")}</span>
          <span className={compact ? "line-clamp-2" : "truncate"}>{source.title}</span>
        </a>
      ))}
    </div>
  );
}

function MissingValue() {
  return <span className="text-mut-2">未披露</span>;
}

function CompanyCard({ rec, onOpen }: { rec: CompanyProfile; onOpen: () => void }) {
  const industry = rec.dims?.["行业"];
  const region = rec.country;
  const detailRows: { label: string; key: string; value: string | null }[] = [
    { label: "行业", key: "industry", value: industry || null },
    { label: "国家 / 地区", key: "country", value: rec.country },
    { label: "团队情况", key: "team", value: rec.team },
    { label: "历史投资人", key: "investors", value: rec.investors },
  ];
  return (
    <article id={`company-card-${rec.id}`} tabIndex={-1} className="ah-card scroll-mt-6 overflow-hidden focus:outline-2 focus:outline-brand">
      <div className="border-b border-line bg-gradient-to-br from-white to-[#f3faf8] px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[17px] font-extrabold tracking-tight text-ink">
              <EvidenceValue value={rec.company_name} evidence={evidenceFor(rec, "company_name")} />
            </h3>
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-mut">
              {rec.product_names.length ? rec.product_names.join(" · ") : "产品信息暂未披露"}
            </p>
            <p className="mt-2 text-[11px] text-mut" title="最新关联报道的发布时间">更新日期：{fmtCnDate(rec.updatedAt || rec.lastSeenAt) || "未披露"}</p>
          </div>
          <span className="shrink-0 rounded-full border border-brand/15 bg-brand-soft px-2.5 py-1 text-[10px] font-bold text-brand">
            {rec.sourceArticles.length} 篇来源
          </span>
        </div>
        {(industry || region) && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {[industry, region].filter(Boolean).map((item) => (
              <span key={item} className="rounded-full border border-brand/10 bg-white px-2.5 py-1 text-[11px] font-medium text-brand-strong">{item}</span>
            ))}
          </div>
        )}
      </div>

      <dl className="grid grid-cols-3 divide-x divide-line border-b border-line">
        {[
          ["成立", rec.founded],
          ["累计融资", rec.total_funding],
          ["最新估值", rec.valuation],
        ].map(([label, value]) => (
          <div key={label} className="min-w-0 px-3 py-3">
            <dt className="text-[10px] font-bold tracking-wide text-mut-2">{label}</dt>
            <dd className="mt-1 truncate text-[12px] font-semibold text-ink-2">{value || "未披露"}</dd>
          </div>
        ))}
      </dl>

      <div className="space-y-4 px-4 py-4 text-[13px] leading-relaxed">
        <div>
          <h4 className="mb-1 text-[11px] font-bold tracking-[0.1em] text-mut">主营业务</h4>
          {rec.business ? <EvidenceValue value={rec.business} evidence={evidenceFor(rec, "business")} className="text-ink-2" /> : <MissingValue />}
        </div>
        <div>
          <h4 className="mb-1.5 text-[11px] font-bold tracking-[0.1em] text-mut">关联报道</h4>
          <SourceLinks rec={rec} compact />
        </div>
      </div>

      <details className="group border-t border-line">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-[12px] font-semibold text-ink-2 hover:bg-surface-2">
          查看团队与投资信息
          <span className="text-brand transition-transform group-open:rotate-180" aria-hidden>⌄</span>
        </summary>
        <dl className="space-y-3 border-t border-line bg-surface-2/55 px-4 py-4 text-[12.5px] leading-relaxed">
          {detailRows.map((row) => (
            <div key={row.key}>
              <dt className="mb-0.5 text-[10px] font-bold tracking-wide text-mut-2">{row.label}</dt>
              <dd>{row.value ? <EvidenceValue value={row.value} evidence={evidenceFor(rec, row.key)} className="text-ink-2" /> : <MissingValue />}</dd>
            </div>
          ))}
        </dl>
      </details>
      {rec.brandProfiles && <details className="border-t border-line">
        <summary className="cursor-pointer px-4 py-3 text-[12px] font-semibold text-brand">旗下品牌与产品资料</summary>
        <div className="space-y-4 px-4 pb-4 text-[12px] leading-relaxed">
          {Object.values(rec.brandProfiles).map((brand) => <div key={brand.id}>
            <h4 className="font-bold text-ink">{brand.company_name}</h4>
            {brand.founded && <p className="text-mut">品牌 / 产品时间：<EvidenceValue value={brand.founded} evidence={evidenceFor(brand, "founded")} /></p>}
            {brand.business && <p><EvidenceValue value={brand.business} evidence={evidenceFor(brand, "business")} /></p>}
            <SourceLinks rec={brand} compact />
          </div>)}
        </div>
      </details>}
      <button type="button" onClick={onOpen} className="w-full border-t border-line px-4 py-3 text-left text-[12px] font-semibold text-brand hover:bg-brand-softer">
        查看完整档案与全部来源
      </button>
    </article>
  );
}

function Pagination({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (page: number) => void }) {
  if (totalPages <= 1) return null;
  return (
    <nav className="mt-5 flex items-center justify-center gap-2" aria-label="公司列表分页">
      <button type="button" disabled={page === 1} onClick={() => onChange(page - 1)} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] text-ink-2 hover:border-brand/35 disabled:cursor-not-allowed disabled:opacity-40">上一页</button>
      <span className="px-2 text-[12px] text-mut">{page} / {totalPages}</span>
      <button type="button" disabled={page === totalPages} onClick={() => onChange(page + 1)} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] text-ink-2 hover:border-brand/35 disabled:cursor-not-allowed disabled:opacity-40">下一页</button>
    </nav>
  );
}

export function CompanyOverviewTable({ overview, dimSel, onDimChange, q, onClearSearch }: {
  overview: CompanyOverview;
  dimSel: DimSelection;
  onDimChange: (next: DimSelection) => void;
  q: string;
  onClearSearch?: () => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const [pagination, setPagination] = useState({ key: "", page: 1 });
  const [selectedCompany, setSelectedCompany] = useState<CompanyProfile | null>(null);
  const filterDimensions = useMemo(() => ({
    industry: { label: "行业", values: [...new Set(overview.companies.map((rec) => rec.dims?.["行业"] || "未披露"))].sort() },
    region: { label: "国家/地区", values: [...new Set(overview.companies.map((rec) => rec.country || "未披露"))].sort() },
  }), [overview]);
  const filteredRows = useMemo(
    () => overview.companies.filter((record) => matches(record, dimSel, q)),
    [overview, dimSel, q],
  );
  const rows = useMemo(() => {
    const sorted = [...filteredRows];
    if (sortKey === "name") sorted.sort((a, b) => a.company_name.localeCompare(b.company_name, "zh-CN"));
    else if (sortKey === "sources") sorted.sort((a, b) => b.sourceArticles.length - a.sourceArticles.length || b.lastSeenAt.localeCompare(a.lastSeenAt));
    else if (sortKey === "products") sorted.sort((a, b) => b.product_names.length - a.product_names.length || b.lastSeenAt.localeCompare(a.lastSeenAt));
    else sorted.sort((a, b) => (Date.parse(b.updatedAt || b.lastSeenAt) || 0) - (Date.parse(a.updatedAt || a.lastSeenAt) || 0));
    return sorted;
  }, [filteredRows, sortKey]);
  const paginationKey = `${q}\u0000${JSON.stringify(dimSel)}\u0000${sortKey}`;
  const requestedPage = pagination.key === paginationKey ? pagination.page : 1;
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const page = Math.min(requestedPage, totalPages);
  const visibleRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const changePage = (nextPage: number) => setPagination({ key: paginationKey, page: nextPage });
  const generatedDate = new Date(overview.generatedAt);
  const generatedAt = overview.generatedAt && !Number.isNaN(generatedDate.getTime())
    ? new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(generatedDate)
    : "—";

  return (
    <section id="company-table" aria-label="公司与产品全景">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-bold tracking-[0.14em] text-brand">COMPANY OVERVIEW</p>
          <h2 className="mt-1 text-[20px] font-extrabold tracking-tight text-ink">公司与产品情报库</h2>
          <p className="mt-1 text-[12px] leading-relaxed text-mut">
            当前显示 {rows.length} / {overview.stats.companiesTotal} 家公司；带来源标记的字段可直接核对原文
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold tracking-[0.12em] text-mut-2">筛选字段</span>
            <TagFilterBar dims={["industry", "region"]} selection={dimSel} onChange={onDimChange} dimsDef={filterDimensions} />
            <button type="button" onClick={() => { onDimChange({}); onClearSearch?.(); }} className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-brand hover:bg-brand-soft">清空筛选与搜索</button>
          </div>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-mut-2">
            <span>更新于 {generatedAt}</span>
            <span>{overview.stats.articlesComplete} 篇已处理</span>
            {overview.stats.articlesDeferred > 0 && <span>{overview.stats.articlesDeferred} 篇待后续批次</span>}
          </div>
          <label className="flex items-center gap-2 text-[11px] text-mut">
            排序
            <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-medium text-ink-2 outline-none focus:border-brand">
              <option value="recent">最近更新</option>
              <option value="name">公司名称</option>
              <option value="sources">报道数量</option>
              <option value="products">产品数量</option>
            </select>
          </label>
        </div>
      </div>

      {!rows.length && <p role="status" className="mb-3 rounded-xl bg-brand-soft p-4 text-[13px] text-ink-2">无匹配公司或产品。可调整上方筛选条件，或清空筛选与搜索。</p>}
      <p className="mb-2 text-[12px] text-mut">点击公司名称查看下方档案；左右滑动表格查看全部字段。</p>
      <div className="ah-card ah-scroll max-h-[65vh] overflow-auto">
        <table aria-label="公司与产品筛选表格" className="min-w-[1910px] border-collapse text-[13px]">
          <thead className="sticky top-0 z-20">
            <tr className="border-b border-line text-left text-mut">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={`whitespace-nowrap bg-surface-2 px-4 py-3 text-[11px] font-bold tracking-wide ${col.key === "company_name" ? "sticky-col" : ""}`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!visibleRows.length && <tr><td colSpan={COLUMNS.length} className="p-6 text-[13px] text-mut">暂无匹配记录</td></tr>}
            {visibleRows.map((rec) => (
              <tr key={rec.id} className="group border-b border-line-2/70 align-top last:border-b-0 hover:bg-[#f5faf9]">
                {COLUMNS.map((col) => {
                  const key = String(col.key);
                  if (col.key === "updatedAt") {
                    return <td key={key} className="px-4 py-3 text-[12px] text-mut" title="最近一次关联报道的发布时间（北京时间）">{fmtCnDate(rec.updatedAt || rec.lastSeenAt) || "未披露"}</td>;
                  }
                  if (col.key === "sourceArticles") {
                    return <td key={key} className={`px-4 py-3.5 leading-relaxed ${col.cellClass}`}><SourceLinks rec={rec} /></td>;
                  }
                  if (col.key === "company_name") {
                    return (
                      <td key={key} className={`px-4 py-3.5 group-hover:bg-[#f5faf9] ${col.cellClass}`}>
                        <a href="#/company" aria-controls={`company-card-${rec.id}`} className="font-bold text-brand underline decoration-brand/30 underline-offset-4 hover:decoration-brand" onClick={(event) => {
                          event.preventDefault();
                          const card = document.getElementById(`company-card-${rec.id}`);
                          card?.focus({ preventScroll: true });
                          card?.scrollIntoView({ behavior: "smooth", block: "start" });
                        }}>{rec.company_name}</a>
                        {rec.aliases.length > 0 && <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-mut-2">别名：{rec.aliases.join("、")}</p>}
                        <button type="button" onClick={() => setSelectedCompany(rec)} className="mt-2 text-[10px] font-bold text-brand hover:underline">查看完整档案</button>
                      </td>
                    );
                  }
                  if (col.key === "industry") {
                    const value = rec.dims?.["行业"] || "";
                    return (
                      <td key={key} className={`px-4 py-3.5 leading-relaxed text-ink-2 ${col.cellClass}`}>
                        {value ? <span className="inline-flex rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-medium text-brand-strong">{value}</span> : <MissingValue />}
                      </td>
                    );
                  }
                  const raw = col.key === "product_names" ? rec.product_names.join("、") : rec[col.key];
                  const value = typeof raw === "string" ? raw : "";
                  return (
                    <td key={key} className={`px-4 py-3.5 leading-relaxed text-ink-2 ${col.cellClass}`}>
                      {value ? <EvidenceValue value={value} evidence={evidenceFor(rec, key)} /> : <MissingValue />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} onChange={changePage} />

      {visibleRows.length > 0 && <section className="mt-8" aria-label="公司详情卡片">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[20px] font-extrabold text-ink">公司与产品档案</h2>
          <a href="#/company" className="text-[12px] font-semibold text-brand" onClick={(event) => { event.preventDefault(); document.getElementById("company-table")?.scrollIntoView({ behavior: "smooth" }); }}>返回筛选表格 ↑</a>
        </div>
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {visibleRows.map((rec) => <CompanyCard key={rec.id} rec={rec} onOpen={() => setSelectedCompany(rec)} />)}
        </div>
      </section>}

      <footer className="mt-7 border-t border-line pt-4 text-center text-[11px] leading-relaxed text-mut-2">
        缺失信息保留为“未披露” · 同名与别名按确定性规则合并 · {overview.coverageNote}
      </footer>
      {selectedCompany && <CompanyDetailDrawer company={selectedCompany} onClose={() => setSelectedCompany(null)} />}
    </section>
  );
}
