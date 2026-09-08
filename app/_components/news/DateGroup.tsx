// 按日期分组容器：日期头（M月D日 · 星期 · N 条）+ 可折叠内容（对齐官网时间轴）
"use client";

import { useState, type ReactNode } from "react";

export function DateGroup({
  monthDay,
  weekday,
  count,
  children,
  defaultOpen = true,
}: {
  monthDay: string;
  weekday?: string;
  count: number;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="mb-7">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-3 flex w-full items-center gap-2 text-left"
        aria-expanded={open}
      >
        <span className="text-[15px] font-bold text-ink">{monthDay}</span>
        <span
          className={`inline-block text-[10px] text-mut-2 transition-transform ${open ? "" : "-rotate-90"}`}
          aria-hidden
        >
          ▼
        </span>
        {weekday && <span className="text-[12.5px] text-mut">{weekday}</span>}
        <span className="text-[12.5px] text-mut">· {count} 条</span>
        <span className="ml-2 h-px flex-1 bg-line" aria-hidden />
      </button>
      {open && <div className="flex flex-col gap-3.5">{children}</div>}
    </section>
  );
}
