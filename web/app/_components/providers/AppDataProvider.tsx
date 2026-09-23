// 全局应用状态：当前视图 + 侧栏开合 + URL hash 同步
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { ViewKey } from "../../_lib/domain/types";
import { viewFromHash } from "../../_lib/domain/navigation";

interface AppState {
  view: ViewKey;
  setView: (v: ViewKey) => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

const AppContext = createContext<AppState | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  // 初始视图惰性读取 hash（客户端渲染阶段执行；SSR 走默认 all）
  const [view, setViewRaw] = useState<ViewKey>(() =>
    typeof window === "undefined" ? "all" : viewFromHash(window.location.hash),
  );
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // 监听浏览器前进/后退
  useEffect(() => {
    const normalizeHash = () => {
      const next = viewFromHash(window.location.hash);
      const normalizedHash = `#/${next}`;
      if (window.location.hash !== normalizedHash) {
        window.history.replaceState(null, "", normalizedHash);
      }
      return next;
    };
    normalizeHash();
    const onHashChange = () => setViewRaw(normalizeHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setView = useCallback((v: ViewKey) => {
    setViewRaw(v);
    setSidebarOpen(false);
    if (typeof window !== "undefined") {
      const target = `#/${v}`;
      if (window.location.hash !== target) {
        window.history.pushState(null, "", target);
      }
    }
  }, []);

  return (
    <AppContext.Provider value={{ view, setView, sidebarOpen, setSidebarOpen }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp 必须在 AppDataProvider 内使用");
  return ctx;
}
