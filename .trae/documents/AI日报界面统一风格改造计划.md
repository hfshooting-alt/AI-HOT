# AI 日报/周报界面统一风格改造计划

## Summary

用户质疑当前 AI 日报的设计：为什么右侧面板只显示"今日看点"摘要 + 占位卡片，还要跳转到旧版 `history/*.html` 归档页？要求改为**在日期栏右侧直接渲染完整日报/周报内容**，与精选/全部AI动态保持统一的卡片风格；旧版完整归档页保留为辅助入口。

改造范围：仅前端 `DailyReportView.tsx` + `api.ts` + `types.ts`，数据源全部已存在（无需后端改动）。

## Current State Analysis

### 现状（为什么会有"跳转旧界面"）

1. **日报**（[DailyReportView.tsx:214-280](../../app/_components/views/DailyReportView.tsx)）：

   * 右侧面板 = VOL 期刊头 + "今日看点"（仅版块名 + 每版块第一条标题，来自 `parseOfficialSections`）+ 虚线占位卡"日报正文尚未产出" + 按钮"查看当日完整归档"→ `entry.url`（如 `history/2026-08-21.html`，旧版界面）。

   * 实际上 `/api/daily?date=YYYY-MM-DD`（[api/daily/route.ts](../../app/api/daily/route.ts) 代理上游）**已返回完整版块与条目**：`report.sections[].items[]` 含 title/summary/source.name/links.original（实测 2026-08-20 返回 14 条、多版块），还有 `flashes[]`（快讯）与 `lead`（导语，当前为 null）。
2. **周报**（[DailyReportView.tsx:283-320](../../app/_components/views/DailyReportView.tsx)）：

   * 右侧面板 = 期刊头 + "本期主线"占位 + 按钮"查看本期周期刊"→ `weekly/{date}.html` 旧页。

   * 实际上 `public/weekly/{weekStart}.json` **静态文件已存在**（build\_snapshot.py 每次构建生成），含 99 条完整 NewsItem（id/title/summary/source/publishedAt/score/classification 等）。
3. 左侧日期/周次归档导航（`snap.history[]` / `snap.weeklyNav[]`）本身没问题，保留。
4. 周报 JSON 中 classification 是 Python 原始格式 `{category: 'release', tags: {...}}`，与前端消费格式 `{cat, dims: [{label, value}]}` 不一致，渲染前需归一化（`category` 值恰好就是新 6 类 id，直接作为 `cat` 使用）。

## Proposed Changes

### 1. [app/\_lib/types.ts](../../app/_lib/types.ts) — 新增日报/周报响应类型

```ts
/** /api/daily 上游日报条目 */
export interface DailyReportItem {
  title: string;
  summary?: string;
  source?: { name?: string };
  links?: { aihot?: string; original?: string };
}

/** /api/daily 上游日报响应（report 包裹层） */
export interface DailyReport {
  date: string;
  lead?: { title?: string; summary?: string } | null;
  sections: { label: string; items: DailyReportItem[] }[];
  flashes?: DailyReportItem[];
}

/** public/weekly/{date}.json 周报期刊 */
export interface WeeklyJournal {
  weekStart: string;
  weekEnd: string;
  volLabel: string;
  finalized: boolean;
  aiReport?: unknown | null;
  items: NewsItem[];
}
```

### 2. [app/\_lib/api.ts](../../app/_lib/api.ts) — 新增两个加载函数

```ts
/** 官方历史日报完整内容（含版块与条目），失败返回 null */
export async function loadDailyReport(date: string): Promise<DailyReport | null> {
  try {
    const data = await fetchJSON<{ report?: DailyReport }>(`/api/daily?date=${date}`);
    return data.report ?? null;
  } catch {
    return null;
  }
}

/** 周报期刊数据（public/weekly/{weekStart}.json），归一化 classification 为前端格式 */
export async function loadWeeklyJournal(weekStart: string): Promise<WeeklyJournal | null> {
  try {
    const data = await fetchJSON<WeeklyJournal>(`/weekly/${weekStart}.json`);
    // classification 原始格式 {category, tags} -> {cat}
    data.items = (data.items || []).map((it) =>
      it.classification && (it.classification as { category?: string }).category
        ? { ...it, classification: { ...it.classification, cat: (it.classification as { category?: string }).category } }
        : it,
    );
    return data;
  } catch {
    return null;
  }
}
```

### 3. [app/\_components/views/DailyReportView.tsx](../../app/_components/views/DailyReportView.tsx) — 核心改造

**日报 DailyDetail 重写**：

* 数据源改为 `loadDailyReport(entry.date)`（替换现有 `parseOfficialSections` 摘要逻辑，state 从 `{label, count, topTitle}[]` 换成 `DailyReport | null`）。

* 渲染结构（与精选页风格一致）：

  * 保留 VOL 期刊头（日期、总条数、定稿状态）。

  * `lead` 存在时渲染导语卡（ah-card，标题 + 摘要）。

  * `flashes` 非空时渲染"快讯"分组卡。

  * **每个 section 渲染为分组卡片**：组头（版块名 + 条数徽标，样式对齐 DateGroup 的组头）+ 条目卡片列表。条目卡片为轻量版（上游日报条目无 id/score/分类）：`ah-card` 内 = 来源 chip + 标题（外链 `links.original`，新标签页）+ 摘要（line-clamp-3），与 ArticleCard 视觉语言一致。

  * 加载中显示骨架卡（对齐精选页 animate-pulse 风格）；`report == null` 时保留现有兜底（今日看点占位结构）。

* **完整归档保留**：期刊头行尾改为小号文字链接"完整归档 →"（`entry.url`，弱化的次要入口），删除占位大按钮。

**周报 WeeklyDetail 重写**：

* 数据源改为 `loadWeeklyJournal(weekStart)`（从 `entry.url` 正则提取 weekStart，现有代码已有此正则）。

* 渲染：期刊头（volLabel、range、总条数）+ 按 `bjDayKey` 分组渲染 `DateGroup` + `ArticleCard`（周报 items 是完整 NewsItem，直接复用现有组件，风格 100% 统一；classification 已归一化，分类角标可正确显示）。

* 同样把"查看本期周期刊"大按钮改为期刊头行尾的"完整归档 →"小链接。

**组件内新增**：

* `ReportItemCard`（日报条目轻量卡片，私有组件，约 30 行）。

* 两个 Detail 组件各自的加载 state + useEffect（selectedDate / selectedWeek 变化时拉取，切换时先清空旧数据，与现有 official 拉取模式一致）。

### 4. 清理

* 删除探索期临时文件 `.trae/tmp_check_daily.py`。

* `parseOfficialSections` 及 `official` state 若不再被兜底使用则删除（兜底直接用 `entry.title` + `entry.total` 的现有占位分支）。

## Assumptions & Decisions

* 日报条目无 score/LLM 分类标签（上游接口不返回），卡片不含评分徽标与分类角标——这是数据事实，非设计遗漏。

* 周报 items 复用 ArticleCard 需归一化 classification（`category` 字段值即新 6 类 id，实测值 'release'/'paper' 等）。

* 左侧归档导航布局不变（用户认可"时间栏右侧直接显示内容"的现有双栏结构）。

* 旧版 `history/*.html`、`weekly/*.html` 归档页与生成管线（build\_snapshot.py）完全不动，仅入口从主按钮降级为次要链接。

* `/api/daily` 对历史日期可用性已实测（2026-08-20/23 均正常返回）。

## Verification

1. dev 服务器热更新后浏览器打开 `http://localhost:3000/#/daily`：

   * 日报 tab：默认选中最新日期，右侧直接显示完整版块分组 + 条目卡片（标题可点开原文），不再出现"日报正文尚未产出"占位大按钮；期刊头行尾有"完整归档 →"小链接且可跳转旧页。

   * 切换左侧其他日期，内容正确刷新（无残留旧日期内容）。

   * 周报 tab：选中某周，右侧按日期分组显示完整 ArticleCard 列表（与精选页卡片风格一致）；"完整归档 →"链接可跳转旧周报页。
2. 日报条目无匹配数据时（如极端日期）显示占位/空态，不白屏。
3. `npx vinext build` 编译通过。
4. 浏览器实测数字抽查：如 2026-08-20 日报应显示 14 条、多个版块；2026-08-10 周报应显示 99 条。

