// 分类 Tab 栏（精选 / 全部动态共用：下划线激活态，对齐截图样式）
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
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-line" role="tablist">
      {options.map((opt) => {
        const on = opt.key === active;
        return (
          <button
            key={opt.key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(opt.key)}
            className={`relative pb-2 text-[13.5px] transition-colors ${
              on ? "font-semibold text-brand-strong" : "text-mut hover:text-ink"
            }`}
          >
            {opt.label}
            {typeof opt.count === "number" && (
              <span className="ml-1 text-[11px] text-mut-2">{opt.count}</span>
            )}
            {on && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-brand" aria-hidden />}
          </button>
        );
      })}
    </div>
  );
}
