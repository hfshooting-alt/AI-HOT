// 公司与产品全景：由全部资讯增量沉淀的独立公司数据库页面。
"use client";

import { useEffect, useMemo, useState } from "react";
import { loadCompanyOverview } from "../../_lib/data/api";
import type { CompanyOverview } from "../../_lib/domain/types";
import { CompanyOverviewTable } from "../company/CompanyOverviewTable";
import { SearchToolbar } from "../news/SearchToolbar";
import { TagFilterBar, type DimSelection } from "../news/TagFilterBar";
import { DatabaseIcon } from "../shared/icons";

const EMPTY_COLUMNS = [
  "公司",
  "代表产品",
  "成立时间",
  "行业",
  "国家 / 地区",
  "主营业务",
  "团队情况",
  "历史投资人",
  "累计融资",
  "最新估值",
  "相关新闻",
];

function MetricCard({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="ah-card relative overflow-hidden px-4 py-4 sm:px-5">
      <span className="absolute top-0 left-0 h-full w-1 bg-brand/70" aria-hidden />
      <p className="text-[11px] font-bold tracking-[0.12em] text-mut-2">{label}</p>
      <p className="mt-2 text-[24px] font-extrabold tracking-tight text-ink">{value}</p>
      <p className="mt-1 text-[11px] leading-relaxed text-mut">{note}</p>
    </div>
  );
}

function EmptyCompanyTable({ dimSel, onDimChange }: {
  dimSel: DimSelection;
  onDimChange: (next: DimSelection) => void;
}) {
  return (
    <section aria-label="公司与产品全景空表">
      <div className="mb-4">
        <p className="text-[11px] font-bold tracking-[0.14em] text-brand">COMPANY OVERVIEW</p>
        <h2 className="mt-1 text-[20px] font-extrabold tracking-tight text-ink">公司与产品情报库</h2>
        <p className="mt-1 text-[12px] text-mut">字段结构已经就绪，首次模型抽取完成后会自动填入公司记录。</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-bold tracking-[0.12em] text-mut-2">筛选字段</span>
          <TagFilterBar dims={["industry", "region"]} selection={dimSel} onChange={onDimChange} />
        </div>
      </div>
      <div className="ah-card ah-scroll overflow-auto">
        <table className="min-w-[1620px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line text-left text-mut">
              {EMPTY_COLUMNS.map((label, index) => (
                <th
                  key={label}
                  className={`whitespace-nowrap bg-surface-2 px-4 py-3 text-[11px] font-bold tracking-wide ${index === 0 ? "sticky left-0 z-10" : ""}`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={EMPTY_COLUMNS.length} className="px-6 py-16 text-center">
                <span className="mx-auto flex size-11 items-center justify-center rounded-2xl bg-brand-soft text-brand">
                  <DatabaseIcon className="size-5" />
                </span>
                <p className="mt-4 text-[14px] font-bold text-ink">公司与产品库等待首次生成</p>
                <p className="mx-auto mt-1.5 max-w-md text-[12px] leading-relaxed text-mut">
                  配置模型 API 后运行 overview 阶段，系统会从全部 AI 动态中提取公司、产品、团队、融资与原文来源。
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function CompanyOverviewView() {
  const [overview, setOverview] = useState<CompanyOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [dimSel, setDimSel] = useState<DimSelection>({});

  useEffect(() => {
    let cancelled = false;
    loadCompanyOverview().then((data) => {
      if (!cancelled) {
        setOverview(data);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const metrics = useMemo(() => {
    const stats = overview?.stats;
    return [
      { label: "COMPANIES", value: stats ? String(stats.companiesTotal) : "—", note: "已归档公司主体" },
      { label: "PRODUCTS", value: stats ? String(stats.productsTotal) : "—", note: "已识别产品与服务" },
      { label: "SOURCES", value: stats ? String(stats.articlesComplete) : "—", note: "已完成结构化的报道" },
    ];
  }, [overview]);

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <p className="mb-2 text-[11px] font-bold tracking-[0.16em] text-brand">INTELLIGENCE DATABASE</p>
          <h1 className="text-[26px] font-extrabold text-ink">公司与产品全景</h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-mut">
            从全部 AI 动态持续沉淀公司与产品信息，并为关键字段保留可回溯的原文证据。
          </p>
        </div>
        <SearchToolbar
          q={q}
          placeholder="搜索公司、产品、业务、团队…"
          onQChange={setQ}
          src="all"
          onSrcChange={() => undefined}
          showSourceFilter={false}
        />
      </header>

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        {metrics.map((metric) => <MetricCard key={metric.label} {...metric} />)}
      </div>

      {loading ? (
        <div className="ah-card h-[340px] animate-pulse bg-surface-2" aria-label="正在加载公司与产品数据" />
      ) : overview?.companies.length ? (
        <CompanyOverviewTable overview={overview} dimSel={dimSel} onDimChange={setDimSel} q={q} onClearSearch={() => setQ("")} />
      ) : (
        <EmptyCompanyTable dimSel={dimSel} onDimChange={setDimSel} />
      )}
    </div>
  );
}
