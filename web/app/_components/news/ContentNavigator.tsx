"use client";

import type { CompanyOverview } from "../../_lib/domain/types";
import { ArrowRightIcon, DatabaseIcon } from "../shared/icons";
import { CategoryTabs, type TabOption } from "./CategoryTabs";

export function ContentNavigator({ options, active, overview, onChange }: {
  options: TabOption[];
  active: string;
  overview: CompanyOverview | null;
  onChange: (key: string) => void;
}) {
  const selected = active === "overview";
  const companies = overview?.stats.companiesTotal ?? 0;
  const products = overview?.stats.productsTotal ?? 0;
  const sources = overview?.stats.articlesComplete ?? 0;
  return (
    <section className="mb-6" aria-label="内容导航">
      <button
        type="button"
        onClick={() => onChange("overview")}
        aria-pressed={selected}
        className={`intel-grid group relative w-full overflow-hidden rounded-2xl border px-5 py-5 text-left transition-all sm:px-6 ${
          selected
            ? "border-brand bg-brand-strong text-white shadow-[0_18px_42px_-24px_rgb(7_94_88/0.9)]"
            : "border-[#196e69] bg-[#0b504d] text-white shadow-[0_18px_42px_-28px_rgb(7_94_88/0.85)] hover:-translate-y-0.5 hover:bg-[#075e58]"
        }`}
      >
        <span className="absolute -top-20 right-0 size-56 rounded-full bg-emerald-300/10 blur-3xl" aria-hidden />
        <span className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-start gap-4">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-white/15 bg-white/10 text-emerald-100">
              <DatabaseIcon />
            </span>
            <span>
              <span className="block text-[11px] font-bold tracking-[0.18em] text-emerald-200/80">COMPANY INTELLIGENCE</span>
              <span className="mt-1 block text-[21px] font-extrabold tracking-tight">公司与产品全景</span>
              <span className="mt-1 block max-w-xl text-[13px] leading-relaxed text-white/65">
                汇总全部新闻中的公司、产品、团队与融资信息，每项资料均可回到原文核对
              </span>
            </span>
          </span>
          <span className="flex items-center gap-5 sm:gap-7">
            <span><strong className="block text-[21px] font-bold">{companies || "—"}</strong><small className="text-[11px] text-white/55">公司</small></span>
            <span><strong className="block text-[21px] font-bold">{products || "—"}</strong><small className="text-[11px] text-white/55">产品</small></span>
            <span><strong className="block text-[21px] font-bold">{sources || "—"}</strong><small className="text-[11px] text-white/55">已处理报道</small></span>
            <span className="flex size-9 items-center justify-center rounded-full border border-white/15 bg-white/10 transition-transform group-hover:translate-x-1"><ArrowRightIcon className="size-4" /></span>
          </span>
        </span>
      </button>

      <div className="mt-5 flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <span className="text-[12px] font-bold tracking-[0.14em] text-mut">资讯分类</span>
          <span className="h-px flex-1 bg-line" />
        </div>
        <CategoryTabs options={options} active={active} onChange={onChange} />
      </div>
    </section>
  );
}
