# AI HOT 静态 HTML 前端改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 `templates/index.template.html` 改造为浅色主题、左侧导航 + 右侧内容区布局，实现精选、热点榜、全部 AI 动态、AI 日报/周报四个模块，并通过 `build_snapshot.py` 生成纯静态 `public/index.html`。

**Architecture:** 保留现有 Python 数据抓取 + 模板渲染链路；在 `templates/index.template.html` 中内嵌完整的浅色主题 CSS 与客户端 JS；`build_snapshot.py` 负责将四类数据注入模板。

**Tech Stack:** 纯 HTML/CSS/JS（无框架），Python 3 数据抓取，AI HOT API。

---

## 1. 现状分析

- `templates/index.template.html` 当前为深色三栏布局。
- `scripts/build_snapshot.py` 已能抓取日报/周报/历史数据。
- `app/_components/` 下已有 Next.js 版本的组件实现，可提供视觉与交互参考。
- 项目通过 `npm run build` 将 `public/` 复制到 `dist/client/` 后启动服务。

---

## 2. 文件结构与职责

```
aihot-site/
├── templates/
│   └── index.template.html      # 新版浅色主题单页模板（CSS + HTML + JS）
├── scripts/
│   └── build_snapshot.py        # 改造：抓取四类数据并渲染模板
├── public/
│   ├── index.html               # 构建产物（由模板生成）
│   └── history/                 # 历史归档页（保持原有逻辑）
└── docs/superpowers/plans/      # 本计划
```

---

## 3. 数据接口规划

| 模块 | Python 函数 | 上游 API | 说明 |
|------|-------------|----------|------|
| 精选 | `fetch_featured()` | `https://aihot.virxact.com/api/public/items?limit=50` | 按 publishedAt 倒序，取评分/热度较高的条目 |
| 热点榜 | `fetch_hot()` | `https://aihot.virxact.com/api/v1/hot-topics` | 热度排序，取前 50 条 |
| 全部 AI 动态 | `fetch_all()` | `https://aihot.virxact.com/api/public/items?limit=200` | 全量条目，用于标签云与分类 |
| 日报/周报 | `fetch_daily_report()` | 本地 `archive/` + 现有构建逻辑 | 按月份组织日报/周报入口 |

---

## 4. 任务拆分

### Task 1: 改造 `templates/index.template.html` 基础布局与浅色主题

**Files:**
- Modify: `templates/index.template.html`

- [ ] **Step 1: 清空原有深色主题 CSS，写入浅色主题变量与全局样式**

```css
:root {
  --bg: #f7f8fa;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --text: #0f172a;
  --muted: #64748b;
  --muted-2: #94a3b8;
  --border: #e2e8f0;
  --border-2: #cbd5e1;
  --accent: #0f766e;
  --accent-soft: #e0f2f1;
  --accent-hover: #ccfbf1;
  --accent-strong: #115e59;
  --shadow: 0 1px 3px rgba(0,0,0,0.05);
  --radius: 12px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
}
```

- [ ] **Step 2: 实现左侧固定导航栏 HTML 结构**

```html
<aside class="sidebar">
  <div class="brand">AI HOT</div>
  <nav class="nav">
    <button data-view="featured" class="nav-item active">精选</button>
    <button data-view="all" class="nav-item">全部 AI 动态</button>
    <button data-view="hot" class="nav-item">热点榜</button>
    <button data-view="daily" class="nav-item">AI 日报</button>
    <button data-view="fav" class="nav-item">收藏</button>
  </nav>
  <div class="sidebar-footer">京ICP备2026012723号-2</div>
</aside>
```

- [ ] **Step 3: 实现右侧主内容区结构（标题 + 分类栏 + 内容容器 + 搜索框）**

```html
<main class="main">
  <header class="main-header">
    <h1 id="page-title">精选</h1>
    <p id="page-desc">AI 筛选的今日重点</p>
    <input id="search" placeholder="搜索标题、摘要…" />
  </header>
  <div id="category-tabs" class="category-tabs"></div>
  <div id="content"></div>
</main>
```

- [ ] **Step 4: 添加导航与分类标签的交互样式（hover / active）**

```css
.nav-item { /* 默认、hover、active 样式 */ }
.category-tab { /* 默认、hover、active 样式 */ }
```

- [ ] **Step 5: 添加响应式布局（移动端隐藏侧栏，顶部汉堡按钮）**

```css
@media (max-width: 768px) {
  .sidebar { display: none; }
  .mobile-header { display: flex; }
}
```

---

### Task 2: 实现模块切换与全局状态

**Files:**
- Modify: `templates/index.template.html`

- [ ] **Step 1: 定义全局状态对象**

```js
const state = {
  view: 'featured',
  category: 'all',
  q: '',
  fav: JSON.parse(localStorage.getItem('aihot_fav') || '[]')
};
```

- [ ] **Step 2: 绑定导航点击事件，切换 view 并重渲染内容区**

```js
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    state.view = btn.dataset.view;
    updateNav();
    render();
  });
});
```

- [ ] **Step 3: 实现 render() 分发器，根据 view 调用对应渲染函数**

```js
function render() {
  const views = { featured, hot, all, daily, fav };
  const fn = views[state.view] || featured;
  fn();
}
```

---

### Task 3: 实现精选模块

**Files:**
- Modify: `templates/index.template.html`
- Modify: `scripts/build_snapshot.py`

- [ ] **Step 1: 在 `build_snapshot.py` 中新增 `fetch_featured()`**

```python
def fetch_featured(api_base, limit=50):
    items = fetch_items(api_base)[:limit]
    # 按 publishedAt 倒序，保留有评分或热度字段的条目
    items.sort(key=lambda i: i.get("publishedAt", ""), reverse=True)
    return items
```

- [ ] **Step 2: 将 featured 数据注入 `DATA`**

```python
data["featured"] = fetch_featured(args.api_base)
```

- [ ] **Step 3: 在模板 JS 中实现 `renderFeatured()`**

```js
function renderFeatured() {
  const items = filterByCategory(DATA.featured, state.category)
    .filter(it => matchesQ(it, state.q));
  const groups = groupByDay(items);
  document.getElementById('content').innerHTML = groups.map(([day, list]) => `
    <div class="date-group">
      <div class="date-header">${day}</div>
      ${list.map(cardHTML).join('')}
    </div>
  `).join('');
}
```

- [ ] **Step 4: 实现单条新闻卡片 HTML 函数**

```js
function cardHTML(item) {
  return `
    <article class="news-card">
      <div class="card-meta">
        <span class="tag">${item.category}</span>
        <span class="source">${esc(item.source)}</span>
        <span class="time">${item.timeText}</span>
        ${item.score ? `<span class="score">AI ${item.score}</span>` : ''}
      </div>
      <h3 class="card-title"><a href="${esc(item.url)}" target="_blank">${esc(item.title)}</a></h3>
      <p class="card-summary">${esc(item.summary)}</p>
    </article>
  `;
}
```

---

### Task 4: 实现热点榜模块

**Files:**
- Modify: `templates/index.template.html`
- Modify: `scripts/build_snapshot.py`

- [ ] **Step 1: 在 `build_snapshot.py` 中新增 `fetch_hot()`**

```python
import urllib.request
def fetch_hot(api_base):
    url = f"{api_base}/api/v1/hot-topics"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

- [ ] **Step 2: 将 hot 数据注入 `DATA`**

```python
try:
    hot_data = fetch_hot(args.api_base)
except Exception:
    hot_data = {"items": []}
data["hot"] = hot_data
```

- [ ] **Step 3: 在模板 JS 中实现 `renderHot()`**

```js
function renderHot() {
  const items = (DATA.hot.items || [])
    .filter(it => state.category === 'all' || it.category === state.category)
    .filter(it => matchesQ(it, state.q));
  document.getElementById('content').innerHTML = `
    <ol class="hot-list">
      ${items.map((it, idx) => hotItemHTML(it, idx + 1)).join('')}
    </ol>
  `;
}
```

- [ ] **Step 4: 实现前三名高亮样式**

```css
.hot-rank-1 { color: #ef4444; }
.hot-rank-2 { color: #f97316; }
.hot-rank-3 { color: #eab308; }
```

---

### Task 5: 实现全部 AI 动态模块

**Files:**
- Modify: `templates/index.template.html`
- Modify: `scripts/build_snapshot.py`

- [ ] **Step 1: 在 `build_snapshot.py` 中新增 `fetch_all()`**

```python
def fetch_all(api_base, limit=200):
    items = fetch_items(api_base)[:limit]
    return items
```

- [ ] **Step 2: 将 all 数据注入 `DATA`**

```python
data["all"] = fetch_all(args.api_base)
```

- [ ] **Step 3: 在模板 JS 中实现标签云与列表渲染**

```js
function renderAll() {
  const tags = extractTags(DATA.all);
  const items = filterByCategory(DATA.all, state.category)
    .filter(it => matchesQ(it, state.q));
  document.getElementById('content').innerHTML = `
    <div class="tag-cloud">${tags.map(tagHTML).join('')}</div>
    <div class="news-list">${items.map(cardHTML).join('')}</div>
  `;
}
```

- [ ] **Step 4: 若分类未完成，展示占位提示**

```js
if (!items.length) {
  html += `<div class="placeholder">自动分类由 AI 生成，持续优化中…</div>`;
}
```

---

### Task 6: 实现 AI 日报/周报模块

**Files:**
- Modify: `templates/index.template.html`
- Modify: `scripts/build_snapshot.py`

- [ ] **Step 1: 复用现有 `archive/` 数据生成日报/周报列表**

```python
def build_daily_nav(all_days):
    nav = {}
    for date_str in sorted(all_days, reverse=True):
        day = all_days[date_str]
        y, m, d = date_str.split('-')
        nav.setdefault(f"{y}-{m}", []).append({"date": date_str, "title": day.get("items", [{}])[0].get("title", "")})
    return nav

data["dailyNav"] = build_daily_nav(all_days)
```

- [ ] **Step 2: 在模板 JS 中实现 `renderDaily()`，左侧月份列表 + 右侧内容**

```js
function renderDaily() {
  const months = Object.keys(DATA.dailyNav);
  document.getElementById('content').innerHTML = `
    <div class="daily-layout">
      <aside class="daily-sidebar">${months.map(monthHTML).join('')}</aside>
      <div class="daily-content">${renderDailyContent(state.selectedDate)}</div>
    </div>
  `;
}
```

- [ ] **Step 3: 实现日报/周报内容以列表/条目形式展示（不使用卡片）**

```js
function dailyItemHTML(item) {
  return `
    <div class="daily-item">
      <div class="daily-item-time">${item.timeText}</div>
      <div class="daily-item-body">
        <a href="${esc(item.url)}" target="_blank">${esc(item.title)}</a>
        <p>${esc(item.summary)}</p>
      </div>
    </div>
  `;
}
```

---

### Task 7: 实现收藏功能

**Files:**
- Modify: `templates/index.template.html`

- [ ] **Step 1: 在新闻卡片上添加收藏按钮**

```html
<button class="fav-btn" data-id="${item.id}">☆</button>
```

- [ ] **Step 2: 实现收藏/取消收藏逻辑并持久化到 localStorage**

```js
document.addEventListener('click', e => {
  const btn = e.target.closest('.fav-btn');
  if (!btn) return;
  toggleFav(btn.dataset.id);
});

function toggleFav(id) {
  const idx = state.fav.indexOf(id);
  if (idx === -1) state.fav.push(id); else state.fav.splice(idx, 1);
  localStorage.setItem('aihot_fav', JSON.stringify(state.fav));
  render();
}
```

- [ ] **Step 3: 实现收藏视图 `renderFav()`，展示已收藏新闻列表**

```js
function renderFav() {
  const items = DATA.featured.filter(it => state.fav.includes(it.id));
  document.getElementById('content').innerHTML = items.map(cardHTML).join('');
}
```

---

### Task 8: 分类标签栏与搜索框

**Files:**
- Modify: `templates/index.template.html`

- [ ] **Step 1: 渲染分类标签并绑定点击事件**

```js
const CATEGORIES = [
  { key: 'all', label: '全部' },
  { key: '模型', label: '模型' },
  { key: '产品', label: '产品' },
  { key: '行业', label: '行业' },
  { key: '论文', label: '论文' },
  { key: '教程', label: '教程' },
  { key: '观点', label: '观点' }
];

function renderTabs() {
  document.getElementById('category-tabs').innerHTML = CATEGORIES.map(c => `
    <button class="category-tab ${state.category === c.key ? 'active' : ''}" data-cat="${c.key}">${c.label}</button>
  `).join('');
}
```

- [ ] **Step 2: 搜索框实时过滤**

```js
document.getElementById('search').addEventListener('input', e => {
  state.q = e.target.value;
  render();
});
```

---

### Task 9: 构建与验证

**Files:**
- Modify: `scripts/build_snapshot.py`
- Modify: `templates/index.template.html`

- [ ] **Step 1: 运行 `build_snapshot.py` 生成新版 `public/index.html`**

```bash
python scripts/build_snapshot.py --no-tags
```

- [ ] **Step 2: 运行 `npm run build` 复制到 `dist/client/`**

```bash
npx vinext build
```

- [ ] **Step 3: 启动静态服务器并在浏览器验证**

```bash
cd dist/client
python -m http.server 3000
```

- [ ] **Step 4: 强刷浏览器，检查浅色主题、导航切换、分类筛选、收藏、日报/周报是否正常**

---

## 5. 验收标准

- [ ] 浏览器强刷后显示浅色风格。
- [ ] 左侧导航包含：精选、全部 AI 动态、热点榜、AI 日报、收藏。
- [ ] 右侧顶部分类标签：全部、模型、产品、行业、论文、教程、观点。
- [ ] 精选模块按时间倒序，支持分类筛选与搜索。
- [ ] 热点榜调用 `/api/v1/hot-topics` 并按热度排序，前三名高亮。
- [ ] 全部 AI 动态展示标签云/列表，支持标签筛选。
- [ ] AI 日报/周报仅保留日报/周报，按月份组织。
- [ ] 收藏功能使用 localStorage 持久化。
- [ ] `public/index.html` 与 `dist/client/index.html` 内容一致且为新版。
- [ ] 本地服务可访问，界面与参考图一致。
