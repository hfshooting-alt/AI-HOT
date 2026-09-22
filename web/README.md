# 新闻Daily 前端

新闻Daily 仅展示 Manus 采集并通过来源、原始发布时间校验的发布批次。首页为“全部文章”，另有“Garena投资精选”和“公司与产品全景”；公司与融资新增由精选生成。AIHOT 日报、热点与实时代理已移除。

浏览器从 `snapshot.json` 的 `all`、`garenaSelected` 两个独立池读取 `manus:` 条目。空池保持空，快照缺失或格式错误明确显示状态，不使用演示新闻、历史日报或浏览器补录回填。摘要或分类缺失的合规文章仍可阅读。最近 24 小时窗口在扫描开始时冻结，“昨天”例外由发布流水线校验；浏览器不会按打开页面的时间移动窗口。

本目录是完整的 Node/vinext 工程根目录。前端源码、包管理器清单和锁文件、Next/Vite/TypeScript/ESLint/PostCSS/Drizzle 配置、公开资源和托管文件均集中在这里。

从仓库根目录运行：

```sh
npm --prefix web ci
npm --prefix web run dev
npm --prefix web test
```

或先 `cd web`，再使用通常的 `npm ci`、`npm run dev`、`npm test`。开发和生产构建使用 `../scripts/vinext.mjs`，固定工程目录并沿用仓库根 `.env`。Python 与设置服务仍从仓库根运行。

| 路径 | 职责 |
| --- | --- |
| `app/` | 网站路由、组件、数据访问与展示工具 |
| `public/` | 公开快照与历史页面，网站 URL 仍为 `/snapshot.json`、`/history/`、`/weekly/` 等 |
| `tests/` | 前端、API、设置服务的 Node 测试 |
| `build/` | Sites 构建插件源码 |
| `worker/`、`db/`、`drizzle/`、`examples/` | Worker 与数据库集成、迁移、可选示例 |
| `.openai/hosting.json` | 当前前端工程的托管配置 |
| `dist/` | 生成的生产构建，忽略提交 |

部署时设置工程根目录为 `web/`。现有仓库 URL 及 GitHub Pages `/AI-HOT/` 路径保留兼容，网站显示名称为“新闻Daily”。前端配置文件保留工具原生文件名，依赖版本保持。
