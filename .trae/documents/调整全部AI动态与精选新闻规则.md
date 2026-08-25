# 调整全部AI动态与精选新闻规则

## 一、概述

根据用户需求，调整两个导航视图的展示规则：

1. **全部AI动态**：要求"尽可能全、尽可能多"，按时间戳倒序排列
2. **精选新闻**：要求 (a) 每天的新闻不超过15条；(b) 展示的是当天最值得关注的新闻，需要有筛选逻辑

## 二、当前状态分析

### 全部AI动态（AllAIView）

**数据链路**：快照（`poolFromSnapshot`） + `/api/all` 实时流（`MAX_PAGES=3`，最多150条）
**当前行为**：已满足"尽可能全、尽可能多 + 时间戳倒序"的要求
- [poolFromSnapshot](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/_lib/api.ts#L74-L88) 从快照daily+weekly合并所有条目，按 `publishedAt` 降序排列
- [AllAIView](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/_components/views/AllAIView.tsx#L26-L57) 将快照池与实时流合并（`mergePools`），按 `publishedAt` 降序排列
- [api/all/route.ts](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/api/all/route.ts#L32-L34) 服务端也按 `publishedAt` 降序排列
- 无任何条数限制，展示所有条目

**结论**：**无需修改**，当前行为已完全满足要求。

### 精选新闻（FeaturedView）

**数据链路**：快照 + `/api/featured` 实时流

**快照侧**（[build_snapshot.py](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/scripts/build_snapshot.py#L829-L832)）：
```python
featured_pool = format_items(items[:200], now_bj)
selected_featured = [it for it in featured_pool if it.get("selected")]
featured_items = selected_featured[:50] if selected_featured else featured_pool[:50]
```
- 优先取 `selected=True` 的条目（最多50条）
- 如果没有 `selected=True` 的条目，回退取前50条

**实时 API 侧**（[api/featured/route.ts](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/api/featured/route.ts#L36)）：
```typescript
let items: NewsItem[] = pool.filter((it) => it.selected !== false);
```
- 只排除 `selected=false`，`selected=undefined/null/true` 全都放行
- **筛选过于宽松**，不符合"当天最值得关注"的要求

**问题**：
1. 实时 API 的 `selected` 筛选太宽松，混入了大量非精选条目
2. 无每日条数上限

## 三、修改方案

### 修改文件1：[app/api/featured/route.ts](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/api/featured/route.ts)

**修改内容**：第36行，将 `selected !== false` 改为 `selected === true`

```typescript
// 修改前
let items: NewsItem[] = pool.filter((it) => it.selected !== false);

// 修改后
let items: NewsItem[] = pool.filter((it) => it.selected === true);
```

**原因**：上游系统（aihot API）的 `selected` 字段标记了"精选"条目。只有 `selected === true` 才表示该条目被明确标记为值得关注，与快照侧的 `selected_featured = [it for it in featured_pool if it.get("selected")]` 逻辑一致。

### 修改文件2：[app/_components/views/FeaturedView.tsx](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/_components/views/FeaturedView.tsx)

#### 修改2a：在 `groups` useMemo 中加每日15条上限

当前代码（第80-95行）：
```typescript
const groups = useMemo(() => {
    const filtered = pool.filter((it) => {
      if (cat !== "all" && it.category !== cat) return false;
      if (src !== "all" && sourceKindOf(it) !== src) return false;
      if (!matchItem(it, q)) return false;
      return true;
    });
    const map = new Map<string, NewsItem[]>();
    for (const it of filtered) {
      const key = bjDayKey(it.publishedAt) || "unknown";
      const arr = map.get(key);
      if (arr) arr.push(it);
      else map.set(key, [it]);
    }
    return [...map.entries()];
  }, [pool, cat, q, src]);
```

修改为：
```typescript
const MAX_FEATURED_PER_DAY = 15;

const groups = useMemo(() => {
    const filtered = pool.filter((it) => {
      if (cat !== "all" && it.category !== cat) return false;
      if (src !== "all" && sourceKindOf(it) !== src) return false;
      if (!matchItem(it, q)) return false;
      return true;
    });
    const map = new Map<string, NewsItem[]>();
    for (const it of filtered) {
      const key = bjDayKey(it.publishedAt) || "unknown";
      const arr = map.get(key);
      if (arr) {
        if (arr.length < MAX_FEATURED_PER_DAY) arr.push(it);
      } else {
        map.set(key, [it]);
      }
    }
    return [...map.entries()];
  }, [pool, cat, q, src]);
```

**原理**：`pool` 已按 `publishedAt` 降序排列（`mergePools` 第100行 + `poolFromSnapshot` 第86行双重排序保证），因此按日分组时，每个组内最先 push 的条目就是该天最新的。达到15条后不再 push，相当于取每天最新15条。筛选顺序：分类Tab → 来源筛选 → 搜索 → 每日上限。

#### 修改2b：更新页面副标题

当前代码（第105行）：
```tsx
<p className="mt-1 text-[13px] text-mut">{today} · AI 筛选的今日重点</p>
```

修改为：
```tsx
<p className="mt-1 text-[13px] text-mut">{today} · AI 精选今日重点（每天最多 15 条）</p>
```

#### 修改2c：`totalShown` 自动反映上限

第97行 `totalShown` 基于 `groups` 计算，`groups` 已包含上限逻辑，所以页脚总数自动正确，无需修改。

## 四、改动的文件汇总

| 文件 | 修改内容 | 原因 |
|------|---------|------|
| [app/api/featured/route.ts](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/api/featured/route.ts) | `selected !== false` → `selected === true` | 严格筛选，只放行明确标记为精选的条目 |
| [app/_components/views/FeaturedView.tsx](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/_components/views/FeaturedView.tsx) | 每日分组加15条上限 + 更新副标题 | 满足"每天不超过15条"要求 |

## 五、不改动的文件

| 文件 | 原因 |
|------|------|
| [app/api/all/route.ts](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/api/all/route.ts) | 全部AI动态无需筛选，全量展示 |
| [app/_components/views/AllAIView.tsx](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/_components/views/AllAIView.tsx) | 已满足全量展示要求 |
| [app/_lib/api.ts](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/_lib/api.ts) | 数据层无需修改 |
| [app/_lib/format.ts](file:///c:/Users/wade.liu/Downloads/Garena/AI%20HOT2/AI%20HOT/ai%20hot-site/aihot-site/app/_lib/format.ts) | 纯工具函数，无需修改 |

## 六、数据流总结

修改后精选新闻的完整数据链路：

```
上游 API (/api/public/items)
  │
  ├─→ /api/featured（服务端）
  │     │  筛选: selected === true（严格）
  │     │  归一化: 分类、sourceType、id 前缀
  │     │  排序: publishedAt 降序
  │     │
  ├─→ Frontend FeaturedView
  │     │  合并: 快照池（build_snapshot 已按 selected 筛选）+ 实时流
  │     │  排序: mergePools 已保证 publishedAt 降序
  │     │  过滤: 分类Tab → 来源筛选 → 搜索
  │     │  上限: 每日分组 ≤ 15 条
  │     │
  └─→ 渲染: DateGroup + ArticleCard
```

## 七、验证步骤

1. `npm run build` — 确保编译通过
2. `npm run dev` — 启动本地开发服务器
3. 打开精选页，观察每日分组是否不超过15条
4. 切换分类 Tab、来源筛选、搜索，验证上限逻辑是否正确
5. 打开全部AI动态页，确认全量展示不受影响