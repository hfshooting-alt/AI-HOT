import type { CompanyProfile } from "../../_lib/domain/types";

export function EntityTypeBadge({ company }: { company: CompanyProfile }) {
  const label = company.entityType === "foundation" ? "基金会"
    : company.entityType === "open_source_organization" ? "开源组织" : null;
  if (!label) return null;
  return <span className="ml-2 inline-block rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold text-brand"
    title={company.entityTypeEvidence?.quote}>{label}</span>;
}
