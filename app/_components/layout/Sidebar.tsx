// 左侧固定导航栏（桌面固定展示，移动端由 AppShell 以抽屉形式复用）
"use client";

import { useApp } from "../providers/AppDataProvider";
import { BrandLogo, FlameIcon, GearIcon, ListIcon, NewsIcon, StarIcon } from "../shared/icons";
import type { ViewKey } from "../../_lib/domain/types";

const NAV_ITEMS: { key: ViewKey; label: string; icon: (p: { className?: string }) => React.ReactNode }[] = [
  { key: "featured", label: "精选", icon: StarIcon },
  { key: "all", label: "全部 AI 动态", icon: ListIcon },
  { key: "hot", label: "热点榜", icon: FlameIcon },
  { key: "daily", label: "AI 日报", icon: NewsIcon },
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
            AI<span className="text-brand"> HOT</span>
          </div>
          <div className="text-[11px] text-mut-2">AI 情报仪表盘</div>
        </div>
      </div>

      {/* 内容导航 */}
      <div className="px-3">
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
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[14px] transition-colors ${
                  active
                    ? "bg-brand-soft font-semibold text-brand-strong"
                    : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                }`}
              >
                <Icon className={`size-4.5 ${active ? "text-brand" : "text-mut"}`} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* 系统导航 */}
      <div className="px-3">
        <div className="px-2 pb-2 text-[11px] font-bold tracking-[0.18em] text-mut-2">系统</div>
        <nav className="flex flex-col gap-1" aria-label="系统导航">
          <button
            type="button"
            onClick={() => setView("settings")}
            aria-current={view === "settings" ? "page" : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[14px] transition-colors ${
              view === "settings"
                ? "bg-brand-soft font-semibold text-brand-strong"
                : "text-ink-2 hover:bg-surface-2 hover:text-ink"
            }`}
          >
            <GearIcon className={`size-4.5 ${view === "settings" ? "text-brand" : "text-mut"}`} />
            设置
          </button>
        </nav>
      </div>

      {/* 底部：备案信息 */}
      <div className="mt-auto px-5 pb-5">
        <div className="mb-3 border-t border-line-2 pt-3 text-[11px] leading-relaxed text-mut-2">
          数据来源：AI HOT 开放 API + 伴生公众号信源
        </div>
        <div className="text-[10.5px] text-mut-2">京ICP备2026012723号-2</div>
      </div>
    </div>
  );
}

/** 桌面端固定侧栏 */
export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[232px] border-r border-line bg-surface lg:block">
      <SidebarContent />
    </aside>
  );
}
