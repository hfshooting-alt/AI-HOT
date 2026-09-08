# AI HOT 前端改造计划（左侧导航 + 四大模块）

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 `public/index.html` 静态快照改造为左侧固定导航 + 右侧主内容区的 AI HOT 站点，支持「精选 / 热点榜 / 全部 AI 动态 / AI 日报」四大模块，视觉与交互对齐提供的 AI HOT 截图。

**Architecture:** 迁移主入口到 Next.js App Router（`app/page.tsx`），以 React + TypeScript + Tailwind CSS 构建 SPA；通过 Next.js API Routes 做 AI HOT API 的代理/聚合层，前端按模块 lazy 加载；保留 `build_snapshot.py` 归档能力，新增 `/api/snapshot` 输出构建数据供前端使用。

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, vinext, Cloudflare Workers（部署目标），AI HOT API（`https://aihot.virxact.com`）。

---

## 1. 现状分析

- 当前主页面是 `public/index.html`，由 `scripts/build_snapshot.py` 生成并内嵌 `const DATA`。
- `app/page.tsx` 目前只做 `redirect("/index.html")`。
- 项目依赖已包含 Next.js / React / Tailwind，但前端逻辑全部写在单一 HTML 内联 JS/CSS 中。
- 后端 Python 脚本已维护好 `archive/` 归档、`public/history/`、`public/weekly/` 等，结构稳定。
- 已有 AI HOT API 端点（记忆确认）：
  - `GET /api/public/items?limit=50&cursor=` 主条目流
  - `GET /api/v1/hot-topics` 热点榜
  - `GET /api/v1/dailies/latest` / `/api/v1/dailies/{date}` 日报
- 当前主题深色，截图风格为浅色白底、左侧深色/彩色导航、卡片式布局。

---

## 2. 总体改造策略

1. **入口迁移**：`app/page.tsx` 不再重定向，渲染新版 AI HOT 首页。
2. **布局**：左侧固定 256px 导航栏 + 右侧可滚动主内容区；移动端左侧抽屉。
3. **状态管理**：React 组件内 `useState` 管理当前 `view`，`useContext` 提供全局数据与缓存；URL hash 同步当前模块。
4. **数据层**：新建 Next.js API Routes，对 AI HOT API 做代理、聚合、缓存，避免前端跨域与暴露密钥。
5. **组件化**：按模块拆分视图组件；复用卡片、标签、日期分组等基础组件。
6. **构建兼容**：保留 `build_snapshot.py`，但改为生成 `public/snapshot.json` 供 `/api/snapshot` 读取；`public/index.html` 保留旧版或 301 到新首页。

---

## 3. 文件结构与职责

```
aihot-site/
├── app/
│   ├── page.tsx                 # 新版首页，渲染 Layout + 当前 View
│   ├── layout.tsx               # 根 layout（字体、全局样式、metadata）
│   ├── globals.css              # 扩展 Tailwind 主题色
│   ├── api/
│   │   ├── featured/route.ts    # 精选数据（聚合 /api/public/items + 归档）
│   │   ├── hot/route.ts        # 热点榜（代理 /api/v1/hot-topics）
│   │   ├── all/route.ts        # 全部 AI 动态（代理 + 分类标签）
│   │   ├── daily/route.ts      # 日报 / 周报（读 archive/ 或官方 dailies）
│   │   └── snapshot/route.ts   # 读取 public/snapshot.json
│   └── _components/
│       ├── Sidebar.tsx          # 左侧导航
│       ├── MobileHeader.tsx     # 移动端顶部汉堡菜单
│       ├── Card.tsx             # 新闻卡片
│       ├── CategoryTabs.tsx     # 顶部分类 Tab
│       ├── DateGroup.tsx        # 按日期分组
│       ├── ScoreBadge.tsx       # AI 评分徽章
│       ├── views/
│       │   ├── FeaturedView.tsx
│       │   ├── HotView.tsx
│       │   ├── AllAIView.tsx
│       │   └── DailyReportView.tsx
│       └── providers/
│           └── AppDataProvider.tsx
├── public/
│   ├── index.html               # 旧版保留（或 301）
│   └── snapshot.json            # build_snapshot.py 新的输出
├── scripts/
│   └── build_snapshot.py        # 改为生成 public/snapshot.json
├── templates/
│   └── snapshot.template.json   # 占位模板
└── docs/superpowers/plans/      # 本计划
```

---

## 4. API 对接计划

| 模块 | 前端调用 | Next.js API | 上游/数据源 | 说明 |
|------|----------|-------------|-------------|------|
| 精选 | `GET /api/featured?category=&q=` | `app/api/featured/route.ts` | `https://aihot.virxact.com/api/public/items` + `public/snapshot.json` | 默认取 48h 精选，支持分类、搜索 |
| 热点榜 | `GET /api/hot` | `app/api/hot/route.ts` | `https://aihot.virxact.com/api/v1/hot-topics` | 实时热度排序，带 60s 缓存 |
| 全部AI动态 | `GET /api/all?tag=&q=` | `app/api/all/route.ts` | `https://aihot.virxact.com/api/v1/items` + LLM 分类 | 暂用上游分类字段；LLM 分类可后续接入 |
| AI日报 | `GET /api/daily?type=daily|weekly&date=` | `app/api/daily/route.ts` | `archive/` JSON + `/api/v1/dailies/{date}` | 日报/周报列表与内容 |
| 快照 | `GET /api/snapshot` | `app/api/snapshot/route.ts` | `public/snapshot.json` | build 产物 |

**缓存策略**：
- `/api/hot`：`Cache-Control: s-maxage=60, stale-while-revalidate=300`
- `/api/featured`、`/api/all`、`/api/daily`：开发阶段无缓存，生产环境按需加 `s-maxage`。

---

## 5. 状态管理与路由

### 5.1 全局状态（React Context）

```ts
interface AppState {
  view: "featured" | "hot" | "all" | "daily";
  sidebarOpen: boolean;
}
```

- `view` 决定右侧渲染哪个视图组件。
- 切换 `view` 时 URL hash 同步：`/#featured`、`/#hot`、`/#all`、`/#daily`。
- 每个视图内部维护自己的 filter state（精选的分类、日报的日期等）。

### 5.2 数据获取

- 使用 `useSWR`（若引入）或原生 `useEffect + fetch`。
- 初始 SSR：从 `/api/snapshot` 预取精选/日报骨架数据，减少白屏。
- CSR：进入视图后按需请求对应 API。

---

## 6. 视觉与交互

### 6.1 配色（参考截图）

```css
:root {
  --bg: #f7f8fa;              /* 页面背景 */
  --surface: #ffffff;          /* 卡片背景 */
  --text: #0f172a;             /* 主文字 */
  --muted: #64748b;            /* 次要文字 */
  --border: #e2e8f0;           /* 边框 */
  --accent: #0f766e;           /* 主品牌青绿 */
  --accent-light: #e0f2f1;     /* 导航选中背景 */
  --rank-1: #ef4444;           /* 热点榜第 1 名 */
  --rank-2: #f97316;           /* 热点榜第 2 名 */
  --rank-3: #eab308;           /* 热点榜第 3 名 */
}
```

### 6.2 布局

- **左侧导航**：固定宽度 256px，高度 100vh，sticky 定位。
  - Logo + 站点名
  - 四个一级导航项：精选、热点榜、全部AI动态、AI日报
  - 底部：主题切换、备案信息
- **右侧主内容区**：flex-1，最大宽度 960px，水平居中或左对齐。
  - 顶部标题区
  - 分类 Tab / 搜索 / 子模块切换
  - 内容列表 / 卡片

### 6.3 响应式

- `lg` 以上：左侧导航展开。
- `md` 以下：左侧导航隐藏为抽屉，顶部显示汉堡按钮。
- 卡片网格：`lg:grid-cols-2 xl:grid-cols-3`；列表视图单列。

---

## 7. 模块详细设计

### 7.1 精选（FeaturedView）

- **数据**：`/api/featured` 返回精选列表（按 `publishedAt` 倒序）。
- **顶部分类 Tab**：全部、模型、产品、行业、论文、教程、观点（与截图一致）。
- **交互**：
  - 默认「全部」，按日期分组展示。
  - 点击分类 Tab 后过滤该分类，仍按日期倒序。
  - 搜索框过滤标题/摘要。
- **卡片字段**：来源、时间、标题、摘要、AI 评分、分类标签、原文链接。

### 7.2 热点榜（HotView）

- **数据**：`/api/hot`。
- **排序**：热度值从高到低。
- **展示**：
  - 当前热点卡片：排名 01/02/03 高亮，热度趋势 mini chart（简化折线）。
  - 事件数统计。
  - 榜单说明文字。
- **字段**：排名、标题、热度值、来源、发布时间、跳转链接。

### 7.3 全部AI动态（AllAIView）

- **优先级最低**，作为占位实现。
- **数据**：`/api/all`。
- **展示**：
  - 标签云/列表（基于上游 `category` 字段）。
  - 点击标签筛选内容。
  - 预留 LLM 分类接口调用位置。
- **占位说明**：若 LLM 分类未接入，使用上游分类字段并提示「自动分类由 AI 生成，持续优化中」。

### 7.4 AI日报（DailyReportView）

- **粒度切换**：日报 / 周报（去除月报）。
- **左侧月份列表**：
  - 日报：每个月下展开该月所有日期。
  - 周报：每个月下展开该月各周。
- **右侧内容**：
  - 日报：显示当日精选摘要、分类统计、占位正文。
  - 周报：显示当周主题、占位正文。
- **数据**：`/api/daily?type=daily|weekly&date=YYYY-MM-DD`。

---

## 8. 后端改造

### 8.1 `scripts/build_snapshot.py`

- 新增 `--json-out public/snapshot.json` 参数。
- 保留 HTML 生成（兼容旧入口），同时输出 `public/snapshot.json`。
- `snapshot.json` 结构：

```json
{
  "daily": { /* 同原 DATA.daily */ },
  "weekly": { /* 同原 DATA.weekly */ },
  "history": [ /* 近 30 天归档导航 */ ],
  "weeklyNav": [ /* 周期刊导航 */ ],
  "generatedAt": "2026-08-18T05:34:14Z"
}
```

### 8.2 新增 API Routes

每个 API route 仅做：
1. 读取上游或本地数据。
2. 简单字段映射/聚合。
3. 返回 JSON。
4. 异常时返回 502/500 及友好错误信息。

---

## 9. 测试计划

1. **本地开发**：`npm run dev` 启动，访问 `/` 查看新版首页。
2. **API 验证**：分别请求 `/api/featured`、`/api/hot`、`/api/daily`、`/api/all` 返回正确 JSON。
3. **交互验证**：
   - 左侧导航切换四个模块平滑无刷新。
   - 精选分类 Tab 过滤正确。
   - 热点榜按热度排序。
   - 日报/周报切换、月份展开、日期选择正常。
4. **响应式**：Chrome DevTools 模拟 iPhone / iPad / Desktop。
5. **构建验证**：`npm run build` 成功，`public/snapshot.json` 被正确生成。

---

## 10. 任务拆分

### Task 1: 项目基础准备

**Files:**
- Modify: `app/layout.tsx`
- Modify: `app/globals.css`
- Modify: `next.config.ts`
- Modify: `app/page.tsx`

- [ ] **Step 1: 更新 layout metadata 为中文，移除重定向逻辑**
- [ ] **Step 2: 在 globals.css 中定义浅色主题变量与 AI HOT 品牌色**
- [ ] **Step 3: 配置 next.config.ts 支持静态导出 / Cloudflare Workers 部署**
- [ ] **Step 4: page.tsx 渲染新版入口组件占位**

### Task 2: 数据 API 层

**Files:**
- Create: `app/api/snapshot/route.ts`
- Create: `app/api/featured/route.ts`
- Create: `app/api/hot/route.ts`
- Create: `app/api/all/route.ts`
- Create: `app/api/daily/route.ts`

- [ ] **Step 1: `/api/snapshot` 读取 public/snapshot.json**
- [ ] **Step 2: `/api/featured` 代理 /api/public/items 并支持 category/q 过滤**
- [ ] **Step 3: `/api/hot` 代理 /api/v1/hot-topics，加 60s 缓存**
- [ ] **Step 4: `/api/all` 代理 /api/v1/items，返回标签聚合结果**
- [ ] **Step 5: `/api/daily` 读取 archive/ 或代理 /api/v1/dailies/{date}，支持 daily/weekly**

### Task 3: 通用组件

**Files:**
- Create: `app/_components/layout/Sidebar.tsx`
- Create: `app/_components/MobileHeader.tsx`
- Create: `app/_components/Card.tsx`
- Create: `app/_components/news/CategoryTabs.tsx`
- Create: `app/_components/news/DateGroup.tsx`
- Create: `app/_components/news/ScoreBadge.tsx`
- Create: `app/_components/providers/AppDataProvider.tsx`

- [ ] **Step 1: Sidebar 固定导航与四个导航项**
- [ ] **Step 2: MobileHeader 汉堡菜单与抽屉联动**
- [ ] **Step 3: Card 新闻卡片，复用评分徽章、标签、来源、时间**
- [ ] **Step 4: CategoryTabs 顶部分类筛选**
- [ ] **Step 5: DateGroup 按日期折叠/展开分组**
- [ ] **Step 6: ScoreBadge AI 评分 ≥80 金色 / 70-79 靛蓝 / <70 弱化**
- [ ] **Step 7: AppDataProvider 提供当前 view 与全局状态**

### Task 4: 精选模块

**Files:**
- Create: `app/_components/views/FeaturedView.tsx`

- [ ] **Step 1: 请求 `/api/featured` 并缓存**
- [ ] **Step 2: 渲染顶部分类 Tab（全部 / 模型 / 产品 / 行业 / 论文 / 教程 / 观点）**
- [ ] **Step 3: 按日期分组倒序渲染卡片列表**
- [ ] **Step 4: 点击分类 Tab 过滤并保留状态**
- [ ] **Step 5: 添加搜索框过滤标题/摘要**

### Task 5: 热点榜模块

**Files:**
- Create: `app/_components/views/HotView.tsx`

- [ ] **Step 1: 请求 `/api/hot`**
- [ ] **Step 2: 按热度值排序渲染 TOP 榜单**
- [ ] **Step 3: 前三名高亮样式与 mini 趋势图占位**
- [ ] **Step 4: 榜单说明文字与标签含义**

### Task 6: AI日报模块

**Files:**
- Create: `app/_components/views/DailyReportView.tsx`

- [ ] **Step 1: 日报/周报 Tab 切换**
- [ ] **Step 2: 左侧按月份组织日期/周次列表**
- [ ] **Step 3: 右侧渲染选中日报/周报占位内容**
- [ ] **Step 4: 保留最终数据结构位置，便于后续填充正文**

### Task 7: 全部AI动态模块

**Files:**
- Create: `app/_components/views/AllAIView.tsx`

- [ ] **Step 1: 请求 `/api/all`**
- [ ] **Step 2: 展示标签云 / 列表**
- [ ] **Step 3: 点击标签筛选内容**
- [ ] **Step 4: 预留 LLM 分类调用位置**

### Task 8: 构建与集成

**Files:**
- Modify: `scripts/build_snapshot.py`
- Create: `templates/snapshot.template.json`
- Modify: `public/index.html`

- [ ] **Step 1: build_snapshot.py 同时输出 public/snapshot.json**
- [ ] **Step 2: 旧 public/index.html 保留或添加 meta refresh 指向新首页**
- [ ] **Step 3: 运行 npm run build 验证**
- [ ] **Step 4: 运行 build_snapshot.py 验证 snapshot.json 生成**

### Task 9: 响应式与细节打磨

**Files:**
- Modify: 各组件

- [ ] **Step 1: 移动端左侧抽屉**
- [ ] **Step 2: 空状态与 loading 骨架屏**
- [ ] **Step 3: 错误边界与重试按钮**
- [ ] **Step 4: 滚动与锚点平滑过渡**

---

## 11. 验收标准

- [ ] 左侧导航固定，四个模块切换无刷新。
- [ ] 精选模块按时间倒序，支持分类过滤与搜索。
- [ ] 热点榜调用 `/api/v1/hot-topics` 并按热度排序。
- [ ] AI日报仅保留日报/周报，月份组织正确，占位内容可扩展。
- [ ] 全部AI动态可展示标签并筛选。
- [ ] 视觉风格与截图一致（浅色、卡片、圆角、阴影、间距）。
- [ ] 移动端左侧导航变为抽屉。
- [ ] `npm run build` 成功，`build_snapshot.py` 正常生成 `snapshot.json`。
