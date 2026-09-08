// 融资动态表格视图：公司维度 10 列融资信息表（构建时由 scripts/funding_table.py 离线生成）
// 纯受控组件：表格数据与筛选状态由父视图传入（数据不可用时父视图回退卡片流）
// 行筛选复用 TagFilterBar 语义：维度内 OR、维度间 AND；搜索词匹配公司/产品/行业/投资人
"use client";

import { useMemo } from "react";
import type { FundingCompany, FundingTable } from "../../_lib/domain/types";
import type { DimSelection } from "../news/TagFilterBar";

/** 固定列序（与 funding_table.py COMPANY_FIELDS 对齐，company_name 为首列） */
const COLUMNS: { key: keyof FundingCompany; label: string; cellClass: string }[] = [
  { key: "company_name", label: "公司名称", cellClass: "sticky-col w-[150px]" },
  { key: "product_name", label: "产品名称", cellClass: "w-[130px]" },
  { key: "founded", label: "公司成立时间", cellClass: "w-[95px]" },
  { key: "country", label: "国家", cellClass: "w-[75px]" },
  { key: "industry", label: "所属行业", cellClass: "w-[130px]" },
  { key: "team", label: "团队情况", cellClass: "w-[230px]" },
  { key: "business", label: "主营业务", cellClass: "w-[230px]" },
  { key: "investors", label: "历史投资人", cellClass: "w-[190px]" },
  { key: "total_funding", label: "累计融资金额", cellClass: "w-[115px]" },
  { key: "valuation", label: "最新估值", cellClass: "w-[105px]" },
  { key: "sourceArticles", label: "来源", cellClass: "w-[200px]" },
];

/** 行筛选：维度内 OR、维度间 AND（与 matchDims 语义一致，键为维度中文 label） */
function matchRowDims(rec: FundingCompany, selection: DimSelection): boolean {
  const active = Object.entries(selection).filter(([, vals]) => vals.length > 0);
  if (!active.length) return true;
  for (const [dimLabel, vals] of active) {
    const v = rec.dims?.[dimLabel];
    if (!v || !vals.includes(v)) return false;
  }
  return true;
}

/** 搜索词匹配：公司/产品/行业/投资人/公司类型/来源标题文本 */
function matchRowQuery(rec: FundingCompany, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    rec.company_name,
    rec.product_name,
    rec.industry,
    rec.investors,
    rec.dims?.["公司类型"],
  ];
  for (const sa of rec.sourceArticles || []) {
    haystack.push(sa.title, sa.mpName || "");
  }
  return haystack.some((f) => (f || "").toLowerCase().includes(needle));
}

/** ISO 时间 → "YYYY-MM-DD HH:mm"（北京时间，构建产物已是北京时区字符串） */
function fmtGeneratedAt(iso: string): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "";
}

interface FundingTableViewProps {
  table: FundingTable;
  /** TagFilterBar 的维度筛选（父视图持有） */
  dimSel: DimSelection;
  /** 搜索词（父视图持有） */
  q: string;
}

export function FundingTableView({ table, dimSel, q }: FundingTableViewProps) {
  /** 行顺序沿用后端排序：最新 sourceArticles[0].publishedAt 倒序 */
  const rows = useMemo(
    () => (table.companies || []).filter((r) => matchRowDims(r, dimSel) && matchRowQuery(r, q)),
    [table, dimSel, q],
  );
  const stats = table.stats || { articlesProcessed: 0, companiesTotal: 0 };
  const anyFilled = (table.companies || []).some((r) => (r.filledBySearch || []).length > 0);

  if (!rows.length) {
    return (
      <p className="ah-card p-8 text-center text-[13px] text-mut">
        无匹配公司，试试清空标签筛选或搜索词。
      </p>
    );
  }

  return (
    <div>
      {/* 说明条：生成时间 + 抽取统计 + 搜索补全说明 */}
      <p className="mb-3 text-[12px] leading-relaxed text-mut-2">
        生成于 {fmtGeneratedAt(table.generatedAt)} · AI 从 {stats.articlesProcessed} 篇融资报道抽取，去重为{" "}
        {stats.companiesTotal} 家公司 · 点击「来源」列标题跳原文
        {anyFilled && " · 标"}
        {anyFilled && (
          <span className="mx-0.5 inline-block rounded bg-brand/10 px-1 text-[10px] font-bold text-brand">
            搜
          </span>
        )}
        {anyFilled && "者为联网搜索补全"}
      </p>

      {/* 宽表格：容器横向滚动，首列吸左侧便于对照公司名 */}
      <div className="ah-card overflow-x-auto">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="border-b border-line text-left text-mut">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={`whitespace-nowrap bg-surface-2 px-3 py-2.5 font-semibold ${
                    col.key === "company_name" ? "sticky-col" : ""
                  }`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((rec) => (
              <tr
                key={rec.id}
                className="border-b border-line-2/60 align-top last:border-b-0 transition-colors hover:bg-surface-2/50"
              >
                  {COLUMNS.map((col) => {
                    const isName = col.key === "company_name";
                    const isSource = col.key === "sourceArticles";
                    const value = isSource
                      ? undefined
                      : (rec[col.key] as string | null | undefined);
                    const filled = (rec.filledBySearch || []).includes(col.key as string);
                    return (
                      <td key={col.key} className={`px-3 py-2.5 text-ink-2 ${col.cellClass}`}>
                        {isName ? (
                          <span
                            className="block truncate font-semibold text-ink"
                            title={rec.company_name}
                          >
                            {rec.company_name}
                          </span>
                        ) : isSource ? (
                          <div className="flex flex-col gap-1">
                            {rec.sourceArticles?.map((sa) => (
                              <a
                                key={sa.id}
                                href={sa.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="block truncate text-ink-2 hover:text-brand"
                                title={sa.title}
                              >
                                {sa.mpName ? `${sa.mpName}：` : ""}
                                {sa.title}
                              </a>
                            ))}
                          </div>
                        ) : value ? (
                          <span className="block truncate" title={value}>
                            {value}
                            {filled && (
                              <span
                                className="ml-1 inline-block rounded bg-brand/10 px-1 align-top text-[10px] font-bold text-brand"
                                title="该字段经联网搜索补全"
                              >
                                搜
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="text-mut-2">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer className="mt-10 border-t border-line pt-5 text-center text-[12px] text-mut-2">
        共 {rows.length} 家公司 · 表格为离线生成产物（约最近一周融资报道） · 字段由 AI 抽取，点击来源列核对原文
      </footer>
    </div>
  );
}
