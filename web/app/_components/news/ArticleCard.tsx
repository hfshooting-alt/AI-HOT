// 新闻条目卡片（精选 / 全部动态共用，对齐官网卡片层级：时间·来源·标签 → 标题 → 摘要 → 评分）
import type { NewsItem } from "../../_lib/domain/types";
import { fmtClock, itemUrl } from "../../_lib/display/format";
import { categoryOf, TAXONOMY_CATEGORY_COLORS, TAXONOMY_LABELS } from "../../_lib/domain/taxonomy";
import { ScoreBadge, SectionTag } from "./ScoreBadge";
import { BookmarkIcon } from "../shared/icons";

export function ArticleCard({ item, showSection = true }: { item: NewsItem; showSection?: boolean }) {
  const wx = item.sourceType === "wechat" || String(item.source || "").startsWith("公众号：");
  const catId = categoryOf(item);
  const color = TAXONOMY_CATEGORY_COLORS[catId] || "#94a3b8";
  return (
    <article className="ah-card ah-card-hover p-5">
      {/* 元信息行 */}
      <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-ink-2">
          <span className="size-1.5 rounded-full bg-ink-2" aria-hidden />
          {fmtClock(item.publishedAt) || item.timeText}
        </span>
        <span
          className={`max-w-[260px] truncate rounded-full border px-2 py-0.5 text-[11.5px] ${
            wx ? "border-emerald-100 bg-emerald-50 text-emerald-700" : "border-line bg-surface-2 text-mut"
          }`}
          title={item.source}
        >
          {item.source || "AI HOT"}
        </span>
        {item.selected !== false && (
          <span className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-brand">
            <span aria-hidden>★</span> 精选
          </span>
        )}
        {showSection && item.category && <SectionTag label={TAXONOMY_LABELS[catId] || catId} color={color} />}
        <span className="ml-auto flex items-center gap-2">
          <ScoreBadge score={item.score} />
          <BookmarkIcon className="size-4 text-mut-2" />
        </span>
      </div>

      {/* 标题 + 摘要 */}
      <h3 className="text-[16px] leading-snug font-bold text-ink">
        <a
          href={itemUrl(item)}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-brand hover:underline decoration-brand/40 underline-offset-4"
        >
          {item.title}
        </a>
      </h3>
      {item.summary && (
        <p className="mt-2 line-clamp-3 text-[13px] leading-relaxed text-mut">{item.summary}</p>
      )}
    </article>
  );
}
