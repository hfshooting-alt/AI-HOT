# 前端工程

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

部署时设置工程根目录为 `web/`。前端配置文件保留工具原生文件名，自动发现和编辑器支持继续有效。依赖版本和两份锁文件内容不变。
