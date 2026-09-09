// 应用外壳：左侧固定导航 + 右侧主内容区；已访问视图保持挂载（hidden 切换，保留筛选状态与滚动）
"use client";

import { useEffect, useState } from "react";
import type { ViewKey } from "../../_lib/domain/types";
import { AppDataProvider, useApp } from "../providers/AppDataProvider";
import { Sidebar, SidebarContent } from "./Sidebar";
import { BrandLogo, CloseIcon, MenuIcon } from "../shared/icons";
import { HotView } from "../views/HotView";
import { AllAIView } from "../views/AllAIView";
import { CompanyOverviewView } from "../views/CompanyOverviewView";
import { DailyReportView } from "../views/DailyReportView";
import { SettingsView } from "../views/SettingsView";

function ShellBody() {
  const { view, sidebarOpen, setSidebarOpen } = useApp();
  const [mounted, setMounted] = useState(false);
  const [visited, setVisited] = useState<Set<ViewKey>>(new Set(["all"]));

  // 客户端挂载后才渲染，避免日期/状态的服务端水合差异（延迟一拍，不产生同步级联渲染）
  useEffect(() => {
    const timer = setTimeout(() => setMounted(true), 0);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisited((prev) => (prev.has(view) ? prev : new Set(prev).add(view)));
    }, 0);
    return () => clearTimeout(timer);
  }, [view]);

  if (!mounted) {
    return <div className="min-h-screen bg-page" />;
  }

  const panel = (key: ViewKey, node: React.ReactNode) => (
    <div className={view === key ? "" : "hidden"} role={view === key ? "main" : undefined}>
      {node}
    </div>
  );

  return (
    <div className="min-h-screen bg-page">
      {/* 桌面固定侧栏 */}
      <Sidebar />

      {/* 移动端顶栏 */}
      <div className="sticky top-0 z-40 flex items-center gap-3 border-b border-line bg-surface px-4 py-3 lg:hidden">
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          aria-label="打开导航"
          className="rounded-lg border border-line p-1.5 text-ink-2 hover:bg-surface-2"
        >
          <MenuIcon />
        </button>
        <BrandLogo className="size-7" />
        <span className="text-[15px] font-extrabold text-ink">
          AI<span className="text-brand"> HOT</span>
        </span>
      </div>

      {/* 移动端抽屉导航 */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="关闭导航"
            onClick={() => setSidebarOpen(false)}
            className="absolute inset-0 bg-black/35"
          />
          <div className="absolute inset-y-0 left-0 w-[264px] bg-surface shadow-xl">
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              aria-label="关闭"
              className="absolute top-4 right-3 rounded-lg p-1.5 text-mut hover:bg-surface-2"
            >
              <CloseIcon />
            </button>
            <SidebarContent />
          </div>
        </div>
      )}

      {/* 主内容区 */}
      <div className="lg:pl-[232px]">
        <main className="mx-auto max-w-[1180px] px-4 py-7 sm:px-6 lg:px-8 lg:py-9">
          {visited.has("all") && panel("all", <AllAIView />)}
          {visited.has("company") && panel("company", <CompanyOverviewView />)}
          {visited.has("hot") && panel("hot", <HotView />)}
          {visited.has("daily") && panel("daily", <DailyReportView />)}
          {visited.has("settings") && panel("settings", <SettingsView />)}
        </main>
      </div>
    </div>
  );
}

export function AppShell() {
  return (
    <AppDataProvider>
      <ShellBody />
    </AppDataProvider>
  );
}
