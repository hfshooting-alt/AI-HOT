# AI HOT

中文 AI 情报看板，聚合 AIHOT API 与 Manus 采集内容，提供精选、全部动态、热点、日报/周报、融资公司表和本地模型设置。

前端使用 React、Next.js API 与 vinext/Vite；数据流水线使用 Python。现有数据以 JSON 快照与归档保存。

## 本地启动

需要 Node.js >=22.13.0 和 Python >=3.10。Windows、macOS、Linux 使用相同的前端命令：

```sh
npm ci
python -m pip install -r requirements.txt
npm run dev
```

也可使用仓库现有的 pnpm 锁文件：`pnpm install --frozen-lockfile`。依赖安装遵循本地包管理器的构建审批策略；不要混用包管理器更新锁文件。

按 `.env.example` 在根目录配置 `.env`，或运行 `node scripts/settings-server.mjs` 后使用设置页。仅查看已有快照无需调用付费采集/模型接口；运行采集需要配置相应密钥。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `npm run dev` | 本地开发 |
| `npm run build` / `npm start` | 生产构建 / 启动 |
| `npm test` | 构建及全部 Node 测试 |
| `npm run test:unit` | 来源、分页和设置服务测试 |
| `python -m unittest discover -s tests -p "test_*.py"` | Python 回归测试 |
| `npm run typecheck` / `npm run lint` | 静态检查；已有问题见维护导航 |
| `python scripts/funding_table.py --selftest` | 融资流程离线自检 |

采集和快照命令会访问外部服务或更新数据，具体参数见运行手册。

## 目录

从[完整目录地图](docs/architecture/DIRECTORY_LAYOUT.md)查看功能分工；[文档入口](docs/README.md)提供阅读顺序。

| 目录/文件 | 职责 |
| --- | --- |
| `app/_components/` | 页面、新闻卡片、日报/周报详情 |
| `app/_lib/`、`app/api/` | 类型、数据读取、展示工具与上游代理 |
| `scripts/manus_source/` | Manus 发现、正文抓取与校验 |
| `scripts/funding/` | 融资输入、抽取、合并、补全与发布 |
| `scripts/*.py` | 稳定 CLI 入口、快照构建、分类与摘要 |
| `public/`、`data/`、`archive/` | 公开快照、流水线数据与历史归档 |
| `build/`、`worker/`、`db/` | 构建插件与部署/数据库脚手架 |
| `tests/` | Python、Node 测试及 fixtures |
| `prompts/`、`templates/` | 提示词与静态归档模板 |
| `config/` | 当前信源、分类参数和候选账号配置 |
| `.github/workflows/` | 自动任务 |

## 维护文档

- [代码维护导航](./docs/architecture/CODEBASE_GUIDE.md)：数据流、修改位置、兼容约定、验证结果。
- [Manus 运行手册](./docs/operations/MANUS_SOURCE_RUNBOOK.md)、[数据契约](./docs/architecture/MANUS_DATA_CONTRACT.md)。
- [部署说明](./docs/operations/DEPLOY_WORKFLOW.md)、[使用说明](./docs/guides/USER_GUIDE.md)。
- [开发守则](./AGENTS.MD)、[当前状态](./CONTEXT.MD)、[长期经验](./MEMORY.MD)。
- [Sites 脚手架参考](./docs/reference/SITES_TEMPLATE.md)：保留原始模板的可选数据库、身份与托管说明。
