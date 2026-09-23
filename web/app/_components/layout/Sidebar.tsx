// 左侧固定导航栏（桌面固定展示，移动端由 AppShell 以抽屉形式复用）
"use client";

import { useApp } from "../providers/AppDataProvider";
import { BrandLogo, DatabaseIcon, ListIcon, NewsIcon } from "../shared/icons";
import type { ViewKey } from "../../_lib/domain/types";

const NAV_ITEMS: { key: ViewKey; label: string; icon: (p: { className?: string }) => React.ReactNode }[] = [
  { key: "all", label: "全部文章", icon: ListIcon },
  { key: "selected", label: "Garena投资精选", icon: NewsIcon },
  { key: "company", label: "公司与产品全景", icon: DatabaseIcon },
];

export function SidebarContent() {
  const { view, setView } = useApp();
  return (
    <div className="flex h-full flex-col">
      {/* 品牌区 */}
      <div className="flex items-center gap-2.5 px-5 pt-6 pb-5">
        <BrandLogo />
        <div className="leading-tight">
          <div className="text-[17px] font-extrabold tracking-wide text-ink">
            新闻<span className="text-brand">Daily</span>
          </div>
          <div className="text-[11px] text-mut-2">多信源新闻与投资研究</div>
        </div>
      </div>

      {/* 内容导航 */}
      <div className="mt-8 px-3">
        <div className="px-2 pb-2 text-[11px] font-bold tracking-[0.18em] text-mut-2">内容</div>
        <nav className="flex flex-col gap-1" aria-label="主导航">
          {NAV_ITEMS.map((item) => {
            const active = view === item.key;
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setView(item.key)}
                aria-current={active ? "page" : undefined}
                className={`relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[14px] transition-all ${
                  active
                    ? "bg-brand-soft font-semibold text-brand-strong shadow-[inset_0_0_0_1px_rgb(18_129_120/0.08)]"
                    : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                }`}
              >
                {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand" aria-hidden />}
                <Icon className={`size-4.5 ${active ? "text-brand" : "text-mut"}`} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* 底部：站点用途 */}
      <div className="mt-auto px-5 pb-5">
        <div className="mb-3 border-t border-line-2 pt-3 text-[11px] leading-relaxed text-mut-2">
          Garena投资部专用
        </div>
      </div>
    </div>
  );
}

/** 桌面端固定侧栏 */
export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[232px] border-r border-line bg-surface/95 shadow-[8px_0_30px_-30px_rgb(7_94_88/0.45)] backdrop-blur lg:block">
      <SidebarContent />
    </aside>
  );
}
