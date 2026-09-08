# 页面组件

阅读顺序：`layout/AppShell.tsx` → `views/` → 对应的功能组件。

| 子目录 | 职责 |
| --- | --- |
| `layout/` | 侧栏、页面切换与整体布局 |
| `providers/` | 应用级数据上下文 |
| `views/` | 精选、全部、热点、日报与设置页面；持有页面交互状态 |
| `news/` | 新闻卡片、日期分组、搜索和标签筛选 |
| `funding/` | 融资公司表及字段展示 |
| `reports/` | 日报与周报的正文、加载和失败状态 |
| `shared/` | 跨功能共用的图标 |

组件通过 `web/app/_lib/data/` 获取数据，类型和枚举来自 `domain/`，格式与来源工具来自 `display/`。页面样式仍在 `web/app/globals.css`；网站路由入口仍在 `web/app/page.tsx` 和 `web/app/api/`。
