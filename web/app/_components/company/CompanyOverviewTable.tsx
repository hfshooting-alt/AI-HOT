"use client";

import { useMemo } from "react";
import type { CompanyFieldEvidence, CompanyOverview, CompanyProfile } from "../../_lib/domain/types";
import type { DimSelection } from "../news/TagFilterBar";

const COLUMNS: { key: keyof CompanyProfile; label: string; cellClass: string }[] = [
  { key: "company_name", label: "公司名称", cellClass: "sticky-col w-[150px]" },
  { key: "product_names", label: "产品名称", cellClass: "w-[140px]" },
  { key: "founded", label: "成立时间", cellClass: "w-[90px]" },
  { key: "country", label: "国家", cellClass: "w-[80px]" },
  { key: "business", label: "主营业务", cellClass: "w-[220px]" },
  { key: "team", label: "团队情况", cellClass: "w-[220px]" },
  { key: "investors", label: "历史投资人", cellClass: "w-[180px]" },
  { key: "total_funding", label: "累计融资金额", cellClass: "w-[120px]" },
  { key: "valuation", label: "最新估值", cellClass: "w-[110px]" },
  { key: "sourceArticles", label: "相关新闻", cellClass: "w-[220px]" },
];

function matches(rec: CompanyProfile, selection: DimSelection, query: string): boolean {
  for (const [label, values] of Object.entries(selection)) {
    if (values.length && !values.includes(rec.dims?.[label])) return false;
  }
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [rec.company_name, ...rec.aliases, ...rec.product_names, rec.business, rec.team,
    rec.investors, rec.dims?.["行业"], rec.dims?.["国家/地区"]]
    .some((value) => (value || "").toLowerCase().includes(q));
}

function evidenceFor(rec: CompanyProfile, key: string): CompanyFieldEvidence[] {
  return rec.fieldSources?.[key] || [];
}

function EvidenceValue({ value, evidence }: { value: string; evidence: CompanyFieldEvidence[] }) {
  const source = evidence[0];
  const title = evidence.length
    ? `来源（${evidence.length}）：${evidence.map((e) => e.title).join("；")}`
    : undefined;
  return source?.url ? (
    <a href={source.url} target="_blank" rel="noopener noreferrer" className="hover:text-brand" title={title}>
      {value}<sup className="ml-1 text-[9px] font-bold text-brand">源{evidence.length}</sup>
    </a>
  ) : <span title={title}>{value}</span>;
}

export function CompanyOverviewTable({ overview, dimSel, q }:
  { overview: CompanyOverview; dimSel: DimSelection; q: string }) {
  const rows = useMemo(() => overview.companies.filter((r) => matches(r, dimSel, q)),
    [overview, dimSel, q]);
  if (!rows.length) {
    return <p className="ah-card p-8 text-center text-[13px] text-mut">无匹配公司或产品，请清空筛选后重试。</p>;
  }
  return (
    <div>
      <p className="mb-3 text-[12px] leading-relaxed text-mut-2">
        从全部新闻类别沉淀 {overview.stats.companiesTotal} 家公司、{overview.stats.productsTotal} 个产品
        {overview.stats.articlesDeferred > 0 && ` · ${overview.stats.articlesDeferred} 篇待后续预算批次处理`}
        {" · 点击带“源”的字段或相关新闻核对原文"}
      </p>
      <div className="ah-card overflow-x-auto">
        <table className="w-full border-collapse text-[12.5px]">
          <thead><tr className="border-b border-line text-left text-mut">
            {COLUMNS.map((col) => <th key={col.key} className={`whitespace-nowrap bg-surface-2 px-3 py-2.5 font-semibold ${col.key === "company_name" ? "sticky-col" : ""}`}>{col.label}</th>)}
          </tr></thead>
          <tbody>{rows.map((rec) => <tr key={rec.id} className="border-b border-line-2/60 align-top last:border-b-0 hover:bg-surface-2/50">
            {COLUMNS.map((col) => {
              const key = String(col.key);
              if (col.key === "sourceArticles") return <td key={key} className={`px-3 py-2.5 ${col.cellClass}`}>
                <div className="flex flex-col gap-1">{rec.sourceArticles.slice(0, 5).map((s) =>
                  <a key={s.id} href={s.url} target="_blank" rel="noopener noreferrer" className="block truncate hover:text-brand" title={s.title}>{s.sourceName ? `${s.sourceName}：` : ""}{s.title}</a>)}</div>
              </td>;
              const raw = col.key === "product_names" ? rec.product_names.join("、") : rec[col.key];
              const value = typeof raw === "string" ? raw : "";
              return <td key={key} className={`px-3 py-2.5 text-ink-2 ${col.cellClass}`}>
                {value ? <EvidenceValue value={value} evidence={evidenceFor(rec, key)} /> : <span className="text-mut-2">未披露</span>}
              </td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>
      <footer className="mt-8 border-t border-line pt-5 text-center text-[12px] text-mut-2">
        当前显示 {rows.length} 家公司 · 缺失信息保留为“未披露” · 同名与别名按确定性规则合并
      </footer>
    </div>
  );
}
