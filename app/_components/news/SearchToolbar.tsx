// 共享搜索工具条：搜索框（标题/摘要/来源/公众号名/URL）+ 来源筛选（一手信源/资讯/推文/公众号）
// 纯受控组件：状态由调用方持有（视图内 setState + 跨导航持久化）
"use client";

import {
  SOURCE_KIND_LABELS,
  SOURCE_KIND_ORDER,
  type SourceKind,
} from "../../_lib/display/source";
import { SearchIcon } from "../shared/icons";

export type SourceFilter = "all" | SourceKind;

export const SOURCE_FILTER_LABELS: Record<SourceFilter, string> = {
  all: "全部",
  ...SOURCE_KIND_LABELS,
};

interface SearchToolbarProps {
  q: string;
  onQChange: (value: string) => void;
  src: SourceFilter;
  onSrcChange: (value: SourceFilter) => void;
  placeholder?: string;
  /** 隐藏来源筛选（融资表格模式：表格行无单一来源属性）；默认显示 */
  showSourceFilter?: boolean;
}

export function SearchToolbar({
  q,
  onQChange,
  src,
  onSrcChange,
  placeholder = "搜索标题、摘要、来源、公众号…",
  showSourceFilter = true,
}: SearchToolbarProps) {
  return (
    <div className="flex w-full max-w-[360px] flex-col gap-2.5 sm:w-auto sm:items-end">
      {/* 搜索框行 */}
      <div className="flex w-full items-center gap-2">
        <label className="relative flex-1">
          <SearchIcon className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-mut-2" />
          <input
            value={q}
            onChange={(e) => onQChange(e.target.value)}
            placeholder={placeholder}
            className="w-full rounded-lg border border-line bg-surface py-2 pr-3 pl-9 text-[13px] text-ink outline-none placeholder:text-mut-2 focus:border-brand focus:ring-2 focus:ring-brand/15"
          />
        </label>
        <button
          type="button"
          className="rounded-lg bg-brand px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-brand-strong"
        >
          搜索
        </button>
      </div>
      {/* 来源筛选行（表格模式下隐藏） */}
      {showSourceFilter && (
        <div className="flex flex-wrap items-center gap-1.5">
          {(Object.keys(SOURCE_FILTER_LABELS) as SourceFilter[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => onSrcChange(key)}
              className={`rounded-full border px-2.5 py-1 text-[12px] transition-colors ${
                src === key
                  ? "border-brand bg-brand text-white"
                  : "border-line bg-surface text-ink-2 hover:border-brand/50"
              }`}
            >
              {SOURCE_FILTER_LABELS[key]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
