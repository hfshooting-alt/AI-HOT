# AI HOT

中文 AI 情报看板，聚合 AIHOT API 与 Manus 采集内容，提供精选、全部动态、热点、日报/周报、跨类别公司与产品库、融资公司表和本地模型设置。

前端使用 React、Next.js API 与 vinext/Vite；数据流水线使用 Python。现有数据以 JSON 快照与归档保存。

## 本地启动

需要 Node.js >=22.13.0 和 Python >=3.10。Windows、macOS、Linux 使用相同的前端命令：

```sh
npm --prefix web ci
python -m pip install -r scripts/requirements.txt
npm --prefix web run dev
```

也可使用仓库现有的 pnpm 锁文件：`pnpm --dir web install --frozen-lockfile`。依赖安装遵循本地包管理器的构建审批策略；不要混用包管理器更新锁文件。

按 `config/env.example` 在根目录配置 `.env`，或运行 `node scripts/settings-server.mjs` 后使用设置页。仅查看已有快照无需调用付费采集/模型接口；运行采集需要配置相应密钥。

## 常用命令

自动更新统一入口：`python scripts/run_pipeline.py doctor` 检查环境；`python scripts/run_pipeline.py run --dry-run` 查看执行计划。配置密钥后用 `python scripts/run_pipeline.py run` 执行采集、公司与产品库及融资表的整套更新，支持 `--resume`、`--stage` 和 `--no-promote`。详见[自动流水线操作说明](docs/operations/AUTOMATED_PIPELINE.md)。

每日任务按北京时间 **10:00 开始**，固定采集前一天 10:00（含）至当天 10:00（不含）的新闻；全部加工成功后更新仓库中的网页产物，并触发 GitHub Pages 重新部署。GitHub 定时调度可能延迟。`--date` 在默认十点模式下表示窗口结束日，旧自然日流程使用 `--window-mode calendar-day`。

当前公开站点使用无后端静态模式，地址为 [https://hfshooting-alt.github.io/AI-HOT/](https://hfshooting-alt.github.io/AI-HOT/)。它读取仓库已有快照，不需要 Manus 或模型 API；在新的采集数据尚未生成时会继续展示现有快照。仓库 Pages Source 已设为 **GitHub Actions**。

| 命令 | 用途 |
| --- | --- |
| `npm --prefix web run dev` | 本地开发 |
| `npm --prefix web run build` / `npm --prefix web start` | 生产构建 / 启动 |
| `npm --prefix web run build:pages` | 生成 `web/dist/client` 静态站点；不访问付费 API |
| `npm --prefix web test` | 构建及全部 Node 测试 |
| `npm --prefix web run test:unit` | 来源、分页和设置服务测试 |
| `python scripts/test_pipeline.py` | Python 离线回归，禁止真实网络/子进程 |
| `python scripts/test_pipeline.py manus-auth` | 只读检查 Manus 认证与余额，结果有缓存 |
| `npm --prefix web run typecheck` / `npm --prefix web run lint` | 静态检查；已有问题见维护导航 |
| `python scripts/build_company_overview.py --no-promote` | 生成并校验公司与产品库；会调用模型 |
| `python scripts/funding_table.py --selftest` | 融资流程离线自检 |

采集和快照命令会访问外部服务或更新数据，具体参数见运行手册。

## 目录

```text
AI-HOT/
├── web/           完整前端工程、配置、锁文件、公开资源和 Node 测试
├── scripts/       数据流水线、提示词、模板、Python 依赖与本地服务
├── config/        信源、分类和环境变量示例
├── data/          Manus/公司与产品/融资数据、每日归档与分类缓存
├── tests/         Python 流水线测试、固定样本与人工评测集
├── docs/          使用指南、架构、运维、开发交接与历史记录
├── .github/       自动任务
├── README.md      项目首页
├── AGENTS.MD      简短开发入口
├── .gitignore     全仓库忽略规则
└── .editorconfig  全仓库编辑规范
```

前端的 `package.json`、两份锁文件及 Vite、Next、TypeScript、ESLint、PostCSS、Drizzle 配置均位于 `web/`。Python 依赖位于 `scripts/requirements.txt`；分类缓存位于 `data/cache/tag_cache.json`；完整交接文档位于 `docs/maintenance/`。

从[完整目录地图](docs/architecture/DIRECTORY_LAYOUT.md)查看详细分工；[文档入口](docs/README.md)提供阅读顺序。

## 维护文档

- [代码维护导航](./docs/architecture/CODEBASE_GUIDE.md)：数据流、修改位置、兼容约定、验证结果。
- [Manus 运行手册](./docs/operations/MANUS_SOURCE_RUNBOOK.md)、[数据契约](./docs/architecture/MANUS_DATA_CONTRACT.md)。
- [部署说明](./docs/operations/DEPLOY_WORKFLOW.md)、[使用说明](./docs/guides/USER_GUIDE.md)。
- [开发守则](./docs/maintenance/AGENTS.MD)、[当前状态](./docs/maintenance/CONTEXT.MD)、[长期经验](./docs/maintenance/MEMORY.MD)。
- [Sites 脚手架参考](./docs/reference/SITES_TEMPLATE.md)：保留原始模板的可选数据库、身份与托管说明。
