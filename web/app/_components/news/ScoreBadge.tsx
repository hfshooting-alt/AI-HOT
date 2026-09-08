// AI 评分徽章：≥80 金色 / 70-79 靛蓝 / <70 弱化（沿用旧仪表盘分级）
export function ScoreBadge({ score }: { score?: number | null }) {
  if (typeof score !== "number") return null;
  const tier = score >= 80 ? "hi" : score >= 70 ? "mid" : "lo";
  const cls =
    tier === "hi"
      ? "text-amber-600 bg-amber-50 border-amber-200"
      : tier === "mid"
        ? "text-indigo-500 bg-indigo-50 border-indigo-200"
        : "text-mut bg-surface-2 border-line";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${cls}`}>
      <span className="size-1.5 rounded-full bg-current opacity-70" aria-hidden />
      AI 评分 {score}/100
    </span>
  );
}

/** 六版块分类标签（带版块色点） */
export function SectionTag({ label, color }: { label: string; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-ink-2 whitespace-nowrap">
      <span className="size-1.5 rounded-full" style={{ background: color || "#94a3b8" }} aria-hidden />
      {label}
    </span>
  );
}
