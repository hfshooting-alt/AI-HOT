// 分类 Tab 栏：紧凑胶囊式导航，适合情报工作台的高频切换。
"use client";

export interface TabOption {
  key: string;
  label: string;
  count?: number;
}

export function CategoryTabs({
  options,
  active,
  onChange,
}: {
  options: TabOption[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="tablist">
      {options.map((opt) => {
        const on = opt.key === active;
        return (
          <button
            key={opt.key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(opt.key)}
            className={`inline-flex min-h-9 items-center rounded-full border px-3.5 py-1.5 text-[13px] transition-all ${
              on
                ? "border-brand bg-brand font-semibold text-white shadow-[0_5px_14px_-8px_rgb(7_94_88/0.9)]"
                : "border-line bg-surface text-mut hover:border-brand/35 hover:bg-brand-softer hover:text-brand-strong"
            }`}
          >
            {opt.label}
            {typeof opt.count === "number" && (
              <span className={`ml-1.5 text-[11px] ${on ? "text-white/70" : "text-mut-2"}`}>{opt.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
