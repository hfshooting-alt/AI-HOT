# docs/maintenance/AGENTS.MD — AI HOT 项目 Agent 开发守则

> 本文件面向所有参与本项目的 coding agent，交接必读。最近同步：2026-09-08。

## 1. 目录地图（先看这里，避免迷路）

| 路径 | 说明 |
|------|------|
| 仓库根目录 | 权威项目目录，所有运行命令从这里执行 |
| `web/app/` | 网站路由与按功能分类的组件、数据工具 |
| `config/` | 当前信源、分类与候选账号配置 |
| `scripts/` | 稳定 CLI 入口、Manus 与融资阶段实现 |
| `tests/` | pipeline、frontend、api、settings 与 fixtures |
| `docs/README.md` | 文档阅读入口 |
| `docs/architecture/DIRECTORY_LAYOUT.md` | 目录分工与路径兼容边界 |
| `docs/architecture/PATH_MIGRATION.json` | 2026-09-08 迁移前后的精确文件路径 |

截图仍按 §7 集中存放。迁移了三份业务配置，显式路径参数使用 `config/` 前缀；脚本命令入口、公开 URL、数据与缓存位置保持稳定。

- Shell 内联命令中的中文路径会被控制台编码破坏：执行脚本时先 `Set-Location`（chdir），或使用 ASCII 引号路径；PowerShell 不支持 `&&`，用分号 `;`。

## 2. 项目定位与架构

AI 情报日报/周报看板：

- **数据链路**：Manus 采集公众号文章（唯一公众号信源，`config/manus_sources.json` 共 20 个账号：group_a 7、group_b 7、group_c 6）→ 两阶段流水线（discovery + content，正文阶段默认由本地脚本爬虫 trafilatura 提取，`MANUS_CONTENT_MODE=manus` 可回退）→ LLM 摘要/分类/打标签 → 原子晋升 `data/manus/current.json` → `build_snapshot.py` 合并 aihot API 数据 → 归档层 `data/archive/YYYY-MM-DD.json` → 生成 `web/public/snapshot.json`、历史页和周报页。
- **融资数据链路**：Manus feed → `scripts/funding_table.py` 抽取融资字段，可选 Tavily 补全 → `data/funding/current.json` / `web/public/funding-table.json` → 前端融资动态表格。
- **前端双形态**：
  - 静态历史产物位于 `web/public/history/`、`web/public/weekly/`；根静态页工作流已停用，`update-snapshot.yml` 已删除；
  - Next.js 16 + React 19 + Tailwind 4 组件化前端（`web/app/` 目录）为当前主形态，`web/app/page.tsx` 直渲染 `AppShell`，侧栏底部含「设置」API Key 配置入口。
- **自动数据更新**：`.github/workflows/fetch-manus.yml` 每日北京时间 01:00 调用 `scripts/run_pipeline.py`，完成采集、feed、快照/归档/历史/周报及融资表，全部成功后发布并提交。操作见 `docs/operations/AUTOMATED_PIPELINE.md`。腾讯云 CloudBase 的线上托管与 Next.js 正式发布切换尚待验证和接通。

## 3. 关键文件与所有权

| 文件/目录 | 归属 | 说明 |
|-----------|------|------|
| `scripts/build_snapshot.py` | 数据/后端 | 快照构建核心：抓取、归档 upsert/finalize/cleanup、自然周引擎、模板渲染 |
| `scripts/manus_source/`（client/config/contracts/pipeline/content_phase/crawler）、`scripts/enrich_news.py`、`scripts/llm_common.py`、`scripts/build_manus_feed.py` | 数据/后端 | Manus 采集与加工流水线（llm_common 自动加载项目根 .env；阶段 B 默认脚本爬虫，依赖 trafilatura） |
| `scripts/prompts/manus_discovery.md` | 数据/后端 | Manus 发现阶段 Prompt；含来源三元组、日期、顺序审计、计数重算及最终 JSON 自检 |
| `scripts/funding_table.py`、`data/funding/`、`web/public/funding-table.json` | 数据/前端 | 融资条目抽取、归档与前端表格数据 |
| `scripts/tag_news.py`、`scripts/eval_tagging.py` | 数据/后端 | AI 打标签 harness 与评测门禁 |
| `scripts/settings-server.mjs` | 工具 | 本地 API Key 设置服务（127.0.0.1:9731，写项目根 `.env`，供 Next.js 设置页调用） |
| `scripts/templates/*.template.html` | 数据侧渲染 | 静态快照模板（index/history/weekly） |
| `web/app/_components/`、`web/app/_lib/`、`web/app/api/` | 前端 | Next.js 组件、数据层、API 路由 |
| `data/archive/`、`web/public/history/`、`web/public/weekly/` | 构建产物 | 归档统一数据源与历史页 |
| `docs/architecture/MANUS_DATA_CONTRACT.md`、`docs/operations/MANUS_SOURCE_RUNBOOK.md` | 契约文档 | 修改流水线前必读 |
| `tests/`、`web/tests/` | 全员 | Python 离线测试 + Node 前端/渲染/设置服务测试，改动后必须全绿 |

## 4. 常用命令（均在权威目录下执行）

```powershell
# 统一入口（doctor 不调用外部 API；dry-run 仅打印计划）
python scripts/run_pipeline.py doctor
python scripts/run_pipeline.py run --dry-run
python scripts/run_pipeline.py run --date 2026-09-07 --no-promote
python scripts/run_pipeline.py run --date 2026-09-07 --resume

# 快照构建（幂等，可重复运行）
python scripts/build_snapshot.py

# Manus 完整生产链路（需要 MANUS_API_KEY；日期示例按需替换）
python scripts/manus_source/runner.py --date 2026-08-27 --groups group_a group_b group_c
python scripts/manus_source/content_phase.py --date 2026-08-27
python scripts/build_manus_feed.py --date 2026-08-27
python scripts/funding_table.py

# 仅试跑 group_a 的发现阶段；默认 Manus 超时为 3600 秒
python scripts/manus_source/runner.py --date 2026-08-27 --groups group_a

# feed 校验但不晋升
python scripts/build_manus_feed.py --date 2026-08-27 --no-promote

# 全部离线测试
python -m pytest tests/ -q
node web/tests/frontend/rendered-html.test.mjs
node web/tests/frontend/source-kind.test.mjs
node web/tests/settings/test_settings_server.mjs

# Next.js 前端
npm --prefix web run dev      # 本地 http://localhost:3000
npm --prefix web run build    # 构建（vinext 输出 dist/）

# API Key 设置服务（Next.js「设置」页写 .env 用，仅监听 127.0.0.1:9731）
node scripts/settings-server.mjs
```

- `runner.py --groups group_a` 只生成 group_a 发现结果。`content_phase.py` 与 `build_manus_feed.py` 仍按生产契约要求 group_a/group_b/group_c 三份发现文件齐全。
- 若确需进行 group_a-only 全链路测试，可为未执行组生成明确的来源失败占位文件；这类 feed 会呈现 `degraded=true`，仅用于流程验证。未得到用户明确授权时使用 `--no-promote`，避免测试数据覆盖正式 feed。
- `MANUS_TIMEOUT_SECONDS` 默认值为 `3600`。长时间 discovery 任务不应再沿用 10 分钟上限。

## 5. Git 纪律（多 session 并行开发）

- main 分支直推；本地提交前先 `git pull --rebase`，避免与 CI 的 Manus feed 提交冲突。
- 若 CI 数据提交与本地分叉：优先重新生成受影响的数据产物后再提交，勿强推。
- 快照类提交使用 `chore: 更新 AI HOT 静态快照 [skip ci]`。
- 提交粒度参考 `docs/history/2026-08-17-manus-only-source-migration-plan.md` §5 的提交边界划分。
- 未经用户明确要求不得 push --force / reset --hard。

## 6. 硬性规范（用户明确要求，违反即返工）

1. **公众号原文链接（mp.weixin.qq.com）必须保留有效**，不得删改或禁用。
2. 不要重写页面、不改新闻数据、不加未经要求的新功能。
3. 日期展示用中文 numeral 格式（如“二〇二六年八月十四日”）；周报 VOL 标识格式 `VOL.2026·八月第 N 周`（周一为一周起点，按月内序号）。
4. 结构化字段（score、publishedAt、category 等）与 AI 叙事内容（摘要/标签）边界分明：UI 展示结构化字段，叙事内容只读消费。
5. 文档与代码必须同步修改：改流水线/契约时同步更新 PIPELINE.md、AGENT.md、README、DISTRIBUTE、使用说明。
6. 写作风格：避免使用先否定 X、再强调 Y 的对照句式（所有对话与文档）。
7. `config/accounts.json` 保留为扩容候选池（WeRead/搜狗已下线，勿恢复旧链路）。

## 7. 截图规范

- 全部截图集中存放在工作区根 `screenshots\` 目录。
- 新截图按功能模块 + 阶段命名，如 `history-archive-ui.png`、`nextjs-featured-top.png`、`qa-stepN-xxx.png`。
- 勿再往根目录散落 png/jpg。

## 8. 交接文档体系

- `docs/maintenance/AGENTS.MD`（本文件）：开发守则。
- `docs/maintenance/CONTEXT.MD`：项目当前状态、实现进度、待办门禁，接手后第二份必读。
- `docs/maintenance/MEMORY.MD`：长期记忆与经验教训精编（按类别），供无记忆系统的 agent 使用。
