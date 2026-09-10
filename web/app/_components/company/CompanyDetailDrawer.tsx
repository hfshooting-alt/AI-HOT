"use client";

import { useEffect } from "react";
import type { CompanyProfile } from "../../_lib/domain/types";
import { CloseIcon } from "../shared/icons";

const FIELD_ROWS: { key: keyof CompanyProfile; label: string }[] = [
  { key: "product_names", label: "代表产品" },
  { key: "founded", label: "成立时间" },
  { key: "country", label: "国家 / 地区" },
  { key: "business", label: "主营业务" },
  { key: "team", label: "团队情况" },
  { key: "investors", label: "历史投资人" },
  { key: "total_funding", label: "累计融资" },
  { key: "valuation", label: "最新估值" },
];

function displayValue(company: CompanyProfile, key: keyof CompanyProfile): string {
  if (key === "product_names") return company.product_names.join("、");
  const value = company[key];
  return typeof value === "string" ? value : "";
}

export function CompanyDetailDrawer({ company, onClose }: {
  company: CompanyProfile;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-labelledby="company-detail-title">
      <button type="button" aria-label="关闭公司详情" onClick={onClose} className="absolute inset-0 bg-[#082f2d]/35 backdrop-blur-[2px]" />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-[560px] flex-col border-l border-line bg-surface shadow-2xl">
        <header className="border-b border-line bg-gradient-to-br from-white to-brand-softer px-5 py-5 sm:px-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[10px] font-bold tracking-[0.16em] text-brand">COMPANY PROFILE</p>
              <h2 id="company-detail-title" className="mt-1 text-[24px] font-extrabold tracking-tight text-ink">{company.company_name}</h2>
              {company.aliases.length > 0 && <p className="mt-1 text-[12px] text-mut">别名：{company.aliases.join("、")}</p>}
              <div className="mt-3 flex flex-wrap gap-1.5">
                {Object.values(company.dims || {}).filter(Boolean).map((value) => (
                  <span key={value} className="rounded-full border border-brand/10 bg-white px-2.5 py-1 text-[11px] font-medium text-brand-strong">{value}</span>
                ))}
              </div>
            </div>
            <button autoFocus type="button" onClick={onClose} aria-label="关闭" className="rounded-xl border border-line bg-white p-2 text-mut hover:border-brand/25 hover:text-brand">
              <CloseIcon className="size-4" />
            </button>
          </div>
        </header>

        <div className="ah-scroll flex-1 overflow-y-auto px-5 py-5 sm:px-6">
          <dl className="grid gap-4 sm:grid-cols-2">
            {FIELD_ROWS.map(({ key, label }) => {
              const value = displayValue(company, key);
              const evidence = (company.fieldSources?.[String(key)] || []).filter((source) => Boolean(source.url));
              return (
                <div key={key} className={key === "business" || key === "team" || key === "investors" ? "sm:col-span-2" : ""}>
                  <dt className="text-[10px] font-bold tracking-[0.12em] text-mut-2">{label}</dt>
                  <dd className="mt-1 text-[13px] leading-relaxed text-ink-2">{value || "未披露"}</dd>
                  {evidence.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {evidence.map((source, index) => (
                        <a
                          key={`${source.articleId}-${index}`}
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold text-brand hover:bg-brand hover:text-white"
                          title={[source.title, source.quote, source.checkedAt ? `核验于 ${source.checkedAt}` : null].filter(Boolean).join(" · ")}
                        >
                          {source.origin === "research" ? "官网核验" : "字段来源"} {index + 1}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </dl>

          <section className="mt-7 border-t border-line pt-5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-[14px] font-bold text-ink">关联报道</h3>
              <span className="text-[11px] text-mut-2">共 {company.sourceArticles.length} 篇</span>
            </div>
            <ol className="mt-3 space-y-2.5">
              {company.sourceArticles.map((source, index) => (
                <li key={`${source.id}-${index}`} className="rounded-xl border border-line bg-surface-2 px-3.5 py-3">
                  {source.url ? (
                    <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-[13px] leading-relaxed font-semibold text-ink-2 hover:text-brand">
                      {source.title}
                    </a>
                  ) : (
                    <p className="text-[13px] leading-relaxed font-semibold text-ink-2">{source.title}</p>
                  )}
                  <p className="mt-1 text-[10px] text-mut-2">{source.sourceName || "来源未标注"} · {source.publishedAt ? source.publishedAt.slice(0, 10) : "时间未知"}</p>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </aside>
    </div>
  );
}
