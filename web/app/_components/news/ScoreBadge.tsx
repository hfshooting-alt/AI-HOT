/** 六版块分类标签（带版块色点） */
export function SectionTag({ label, color }: { label: string; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-ink-2 whitespace-nowrap">
      <span className="size-1.5 rounded-full" style={{ background: color || "#94a3b8" }} aria-hidden />
      {label}
    </span>
  );
}
