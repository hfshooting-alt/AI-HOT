# 数据流水线和工具入口

根层脚本保持原命令路径，业务阶段实现放入对应子目录。所有命令从仓库根运行。

| 功能 | 入口/实现 | 主要输入 → 输出 |
| --- | --- | --- |
| 测试与成本控制 | `test_pipeline.py`、`testing/` | 默认离线回归；Manus 认证/问答与 LLM 极小 JSON 探针 → `work/test-cost/` |
| 统一检查/运行/恢复 | `run_pipeline.py`、`automation/` | full 或 aihot-only → 隔离候选 → 校验发布；见[操作说明](../docs/operations/AUTOMATED_PIPELINE.md) |
| Manus 发现与正文 | `manus_source/runner.py`、`content_phase.py` | `config/manus_sources.json`、`scripts/prompts/` → `work/manus/` |
| 正文加工与分类 | `enrich_news.py`、`tag_news.py`、`llm_common.py` | 正文、`config/taxonomy.json` → 摘要、标签 |
| Feed 发布 | `build_manus_feed.py` | Manus 工作产物 → `data/manus/` |
| 快照与日报/周报 | `build_snapshot.py` | AIHOT API、Manus feed、`data/archive/` → `web/public/` |
| 融资公司表 | `funding_table.py`、`funding/` | 快照/feed → `data/funding/`、`web/public/funding-table.json` |
| 人工标注与评测 | `make_annotation_sheet.py`、`eval_tagging.py` | 归档与标注集 → `tests/evaluation/` 与指标 |
| 静态快照提取工具 | `extract_snapshot.mjs` | 旧静态 HTML → JSON |
| 本地设置服务 | `settings-server.mjs` | 设置页请求 → 根目录 `.env` |
| 前端开发与构建 | `vinext.mjs` | 跨平台调用 vinext，构建输出 `web/dist/` |

执行细节见 [运行手册](../docs/operations/MANUS_SOURCE_RUNBOOK.md)，字段契约见 [数据契约](../docs/architecture/MANUS_DATA_CONTRACT.md)。

统一入口默认十点 24 小时窗口；时间边界实现在 `manus_source/window.py`，发现提示词为 `prompts/manus_discovery_window.md`。原始产物和恢复状态使用 ten-am 子目录，旧自然日模式仍可显式选择。
