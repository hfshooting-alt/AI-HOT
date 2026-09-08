// 维度标签筛选条：当前类别的维度按钮（行业/国家·地区…），点击展开下拉勾选
// 多选语义由数据层 matchDims 决定：维度内 OR、维度间 AND；纯受控组件
"use client";

import { useEffect, useRef, useState } from "react";
import { TAXONOMY_DIMENSIONS } from "../../_lib/domain/taxonomy";

export type DimSelection = Record<string, string[]>;

interface TagFilterBarProps {
  /** 当前类别的维度 id 列表（如 ["industry", "region"]） */
  dims: readonly string[];
  /** 已选标签（key 为维度中文名，与 classification.dims.label 对齐） */
  selection: DimSelection;
  onChange: (next: DimSelection) => void;
  /** 可选维度定义注入；缺省使用全局 TAXONOMY_DIMENSIONS（其余 Tab 行为不变） */
  dimsDef?: Record<string, { label: string; values: string[] }>;
}

function ChevronDownIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={`size-3.5 ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CheckIcon({ className = "size-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M3.5 8.5l3 3 6-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DimDropdown({
  dimId,
  selected,
  onToggle,
  onClear,
  dimsDef,
}: {
  dimId: string;
  selected: string[];
  onToggle: (value: string) => void;
  onClear: () => void;
  dimsDef?: Record<string, { label: string; values: string[] }>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const dim = (dimsDef ?? TAXONOMY_DIMENSIONS)[dimId];

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  if (!dim) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] transition-colors ${
          selected.length
            ? "border-brand bg-brand text-white"
            : "border-line bg-surface text-ink-2 hover:border-brand/50"
        }`}
      >
        {dim.label}
        {selected.length > 0 && <span className="text-[11px] font-bold">{selected.length}</span>}
        <ChevronDownIcon className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 z-30 mt-1.5 w-52 rounded-xl border border-line bg-surface p-2 shadow-lg">
          <div className="max-h-64 overflow-y-auto">
            {dim.values.map((v) => {
              const on = selected.includes(v);
              return (
                <label
                  key={v}
                  className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[12.5px] text-ink-2 transition-colors hover:bg-surface-2"
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => onToggle(v)}
                    className="sr-only"
                  />
                  <span
                    className={`flex size-4 shrink-0 items-center justify-center rounded border ${
                      on ? "border-brand bg-brand text-white" : "border-line-2 bg-surface"
                    }`}
                    aria-hidden
                  >
                    {on && <CheckIcon />}
                  </span>
                  {v}
                </label>
              );
            })}
          </div>
          {selected.length > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="mt-1 w-full rounded-lg px-2.5 py-1.5 text-left text-[12px] text-mut transition-colors hover:bg-surface-2 hover:text-ink"
            >
              清空{dim.label}筛选
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function TagFilterBar({ dims, selection, onChange, dimsDef }: TagFilterBarProps) {
  if (!dims.length) return null;
  const dimensions = dimsDef ?? TAXONOMY_DIMENSIONS;
  const toggle = (dimLabel: string, value: string) => {
    const cur = selection[dimLabel] || [];
    const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
    onChange({ ...selection, [dimLabel]: next });
  };
  const clear = (dimLabel: string) => {
    const next = { ...selection };
    delete next[dimLabel];
    onChange(next);
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {dims.map((dimId) => {
        const dim = dimensions[dimId];
        if (!dim) return null;
        return (
          <DimDropdown
            key={dimId}
            dimId={dimId}
            selected={selection[dim.label] || []}
            onToggle={(v) => toggle(dim.label, v)}
            onClear={() => clear(dim.label)}
            dimsDef={dimsDef}
          />
        );
      })}
    </div>
  );
}
