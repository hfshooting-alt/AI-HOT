# 目录分工与文件溯源

## 根目录

根目录只保留项目首页、简短开发入口和仓库通用规则。功能代码、工具配置、数据、文档都归入以下目录：

| 目录 | 维护内容 |
| --- | --- |
| `web/` | 完整前端工程：app、public、Node 清单与锁文件、框架配置、托管、构建工具与 Node 测试 |
| `scripts/` | Python CLI、Manus/公司库/融资阶段、prompts、templates、requirements.txt、本地设置服务与前端启动工具 |
| `config/` | taxonomy、生产与候选信源、env.example |
| `data/` | manus、company-overview、funding、archive、cache |
| `tests/` | pipeline、fixtures、evaluation |
| `docs/` | guides、architecture、operations、reference、maintenance、history |
| `.github/` | 自动任务 |

前端内部的组件继续按 layout/providers/views/news/company/funding/reports/shared 划分，工具按 data/domain/display 分层。各目录 README 提供入口与依赖关系。

自动运行的编排代码集中在 `scripts/automation/`，命令入口为 `scripts/run_pipeline.py`。运行状态、候选产物和发布前备份位于已忽略的 `work/runs/`；操作说明在 `docs/operations/AUTOMATED_PIPELINE.md`。

## 启动和路径

从仓库根执行：

```sh
npm --prefix web ci
npm --prefix web run dev
npm --prefix web test
npm --prefix web run build:pages
python -m pip install -r scripts/requirements.txt
python -m unittest discover -s tests -p "test_*.py"
python scripts/funding_table.py --selftest
```

也可进入 `web/` 后使用 `npm run dev` 等原生命令。生产构建输出 `web/dist/`；GitHub Pages 上传 `web/dist/client/`，由 `scripts/build_pages.mjs` 校验首页并补充 `.nojekyll` 与 `404.html`。

环境变量样例为 `config/env.example`，本地密钥仍写仓库根 `.env`，由前端启动工具、Python 和设置服务共用。根 `.env` 被忽略，不提交。

Python CLI 文件路径保持不变，默认输入/输出跟随目录迁移：公开资源 `web/public/`，每日归档 `data/archive/`，分类缓存 `data/cache/tag_cache.json`，提示词/模板 `scripts/prompts/`、`scripts/templates/`，评测集 `tests/evaluation/`。显式填写旧路径的个人命令或环境变量需按迁移表调整。

网站公开 URL 仍为 `/snapshot.json`、`/funding-table.json`、`/history/`、`/weekly/` 等。配置、提示词、模板、新闻数据、缓存和锁文件原样迁移，不重新生成内容。

## 历史追踪

- 第一次按功能归类：以 `438aaef` 为基线，映射见 [PATH_MIGRATION.json](PATH_MIGRATION.json)。
- 本次收拢整个根目录：以 `8cb2bed` 为基线，映射见 [ROOT_PATH_MIGRATION.json](ROOT_PATH_MIGRATION.json)。前一份映射记录当时的路径，必要时串联两份表查找当前路径。
- `git log --follow -- <新路径>` 查看文件迁移前后的历史；`git blame <新路径>` 查看行来源。

历史方案集中于 `docs/history/`，保留原始设计语境；执行操作以当前 README 和运行手册为准。完整 Agent 守则和交接文档在 `docs/maintenance/`，根 `AGENTS.MD` 保留自动发现入口。

`node_modules/`、`dist/`、`.vinext/`、`.wrangler/`、`__pycache__/` 等本地生成目录已忽略提交。缓存化的本机依赖可以复用，不影响 GitHub 的目录布局。
