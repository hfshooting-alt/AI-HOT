# 自动运行模块

CLI：`../run_pipeline.py`。操作说明见 [自动数据流水线](../../docs/operations/AUTOMATED_PIPELINE.md)。

| 模块 | 职责 |
| --- | --- |
| `doctor.py` | 本地配置、依赖、输入与写权限检查 |
| `runner.py` | 阶段命令、候选目录、状态、恢复与发布前验证 |
| `publish.py` | 固定输出目录的备份替换、日志和失败恢复 |

业务规则继续由 Manus、快照和融资模块维护；这里复用其 CLI。测试位于 `tests/pipeline/test_automation.py`，外部调用使用固定样本替代。
