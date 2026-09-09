"use client";

import { useMemo } from "react";
import type { CompanyFieldEvidence, CompanyOverview, CompanyProfile } from "../../_lib/domain/types";
import type { DimSelection } from "../news/TagFilterBar";
import { ArrowRightIcon } from "../shared/icons";

const COLUMNS: { key: keyof CompanyProfile; label: string; cellClass: string }[] = [
  { key: "company_name", label: "公司", cellClass: "sticky-col w-[190px]" },
  { key: "product_names", label: "代表产品", cellClass: "w-[170px]" },
  { key: "founded", label: "成立时间", cellClass: "w-[100px]" },
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
    if (values.length && !values.includes(rec.dims?.[label])) return false;
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

function MobileCompanyCard({ rec }: { rec: CompanyProfile }) {
  const industry = rec.dims?.["行业"];
  const region = rec.dims?.["国家/地区"];
  return (
    <article className="ah-card overflow-hidden">
      <div className="border-b border-line bg-gradient-to-br from-white to-[#f3faf8] px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[17px] font-extrabold tracking-tight text-ink">
              <EvidenceValue value={rec.company_name} evidence={evidenceFor(rec, "company_name")} />
            </h3>
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-mut">
              {rec.product_names.length ? rec.product_names.join(" · ") : "产品信息暂未披露"}
            </p>
          </div>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-brand/15 bg-brand-soft text-brand">
            <ArrowRightIcon />
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
    </article>
  );
}

export function CompanyOverviewTable({ overview, dimSel, q }: {
  overview: CompanyOverview;
  dimSel: DimSelection;
  q: string;
}) {
  const rows = useMemo(
    () => overview.companies.filter((record) => matches(record, dimSel, q)),
    [overview, dimSel, q],
  );
  const generatedAt = overview.generatedAt
    ? new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(overview.generatedAt))
    : "—";

  if (!rows.length) {
    return <p className="ah-card p-10 text-center text-[13px] text-mut">无匹配公司或产品，请清空筛选后重试。</p>;
  }

  return (
    <section aria-label="公司与产品全景">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-bold tracking-[0.14em] text-brand">COMPANY OVERVIEW</p>
          <h2 className="mt-1 text-[20px] font-extrabold tracking-tight text-ink">公司与产品情报库</h2>
          <p className="mt-1 text-[12px] leading-relaxed text-mut">
            当前显示 {rows.length} / {overview.stats.companiesTotal} 家公司；带来源标记的字段可直接核对原文
          </p>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-mut-2">
          <span>更新于 {generatedAt}</span>
          <span>{overview.stats.articlesComplete} 篇已处理</span>
          {overview.stats.articlesDeferred > 0 && <span>{overview.stats.articlesDeferred} 篇待后续批次</span>}
        </div>
      </div>

      <div className="grid gap-3 md:hidden">
        {rows.map((rec) => <MobileCompanyCard key={rec.id} rec={rec} />)}
      </div>

      <div className="ah-card ah-scroll hidden max-h-[72vh] overflow-auto md:block">
        <table className="min-w-[1770px] border-collapse text-[13px]">
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
            {rows.map((rec) => (
              <tr key={rec.id} className="group border-b border-line-2/70 align-top last:border-b-0 hover:bg-[#f5faf9]">
                {COLUMNS.map((col) => {
                  const key = String(col.key);
                  if (col.key === "sourceArticles") {
                    return <td key={key} className={`px-4 py-3.5 leading-relaxed ${col.cellClass}`}><SourceLinks rec={rec} /></td>;
                  }
                  if (col.key === "company_name") {
                    return (
                      <td key={key} className={`px-4 py-3.5 group-hover:bg-[#f5faf9] ${col.cellClass}`}>
                        <EvidenceValue value={rec.company_name} evidence={evidenceFor(rec, key)} className="font-bold text-ink" />
                        {rec.aliases.length > 0 && <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-mut-2">别名：{rec.aliases.join("、")}</p>}
                        <div className="mt-2 flex flex-wrap gap-1">
                          {[rec.dims?.["行业"], rec.dims?.["国家/地区"]].filter(Boolean).map((item) => (
                            <span key={item} className="rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-medium text-brand-strong">{item}</span>
                          ))}
                        </div>
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

      <footer className="mt-7 border-t border-line pt-4 text-center text-[11px] leading-relaxed text-mut-2">
        缺失信息保留为“未披露” · 同名与别名按确定性规则合并 · {overview.coverageNote}
      </footer>
    </section>
  );
}
