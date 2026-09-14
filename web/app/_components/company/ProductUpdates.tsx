import type { CompanyProfile } from "../../_lib/domain/types";
const LABELS = { owned: "自有", integrated: "集成", used: "使用", unknown: "关系待核实" };
export function productText(company: CompanyProfile): string {
  return company.product_names.map(name => {
    const entries = (company.productUpdates || []).filter(p => p.name === name);
    const relations = [...new Set(entries.map(p => LABELS[p.relationship]))];
    return `${name}（${relations.join("／") || LABELS.unknown}）`;
  }).join("、");
}
export function ProductUpdates({ company }: { company: CompanyProfile }) {
  return <div className="space-y-2">{(company.productUpdates || []).map((p, i) => <div key={`${p.articleId}-${p.name}-${i}`} className="rounded-lg border border-line bg-surface-2 px-3 py-2">
    <span className="font-semibold">{p.name}</span><span className="ml-2 text-[11px] text-brand">{LABELS[p.relationship]}</span>
    <div className="mt-1 text-[11px] text-mut">{p.publishedAt ? new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai", year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(p.publishedAt)) : "日期待核实"}{p.url && <> · <a href={p.url} target="_blank" rel="noopener noreferrer" className="text-brand hover:underline" title={p.quote}>{p.title || "关联报道"}</a></>}</div>
  </div>)}</div>;
}
