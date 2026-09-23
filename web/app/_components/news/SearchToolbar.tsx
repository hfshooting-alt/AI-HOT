// 共享搜索工具条：按标题、摘要、来源、公众号名或 URL 搜索。
// 纯受控组件：状态由调用方持有（视图内 setState + 跨导航持久化）
"use client";

import { SearchIcon } from "../shared/icons";

interface SearchToolbarProps {
  q: string;
  onQChange: (value: string) => void;
  placeholder?: string;
}

export function SearchToolbar({
  q,
  onQChange,
  placeholder = "搜索标题、摘要、来源、公众号…",
}: SearchToolbarProps) {
  return (
    <div className="flex w-full max-w-[360px] flex-col gap-2.5 sm:w-auto sm:items-end">
      {/* 搜索框行 */}
      <form className="flex w-full items-center gap-2" onSubmit={(event) => event.preventDefault()} role="search">
        <label className="relative flex-1">
          <span className="sr-only">搜索资讯</span>
          <SearchIcon className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-mut-2" />
          <input
            value={q}
            onChange={(e) => onQChange(e.target.value)}
            placeholder={placeholder}
            className="w-full rounded-xl border border-line bg-surface py-2.5 pr-3 pl-9 text-[13px] text-ink shadow-[0_1px_2px_rgb(16_42_42/0.03)] outline-none placeholder:text-mut-2 focus:border-brand focus:ring-3 focus:ring-brand/10"
          />
        </label>
        <button
          type="submit"
          className="rounded-xl bg-brand px-4 py-2.5 text-[13px] font-semibold text-white shadow-[0_6px_16px_-9px_rgb(7_94_88/0.8)] transition-colors hover:bg-brand-strong"
        >
          搜索
        </button>
      </form>
    </div>
  );
}
