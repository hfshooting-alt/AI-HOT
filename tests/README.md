# 测试入口

| 目录 | 内容 | 执行方式 |
| --- | --- | --- |
| `pipeline/` | 169 项 Python 流水线测试 | `python -m unittest discover -s tests -p "test_*.py"` |
| `evaluation/` | 人工标注与分类评测样本 | 由标注/评测脚本读取 |
| `../web/tests/` | 前端、API、设置服务 | `npm --prefix web test` |
| `fixtures/` | Manus JSON 与正文 HTML 样本 | 由流水线测试读取 |

`npm --prefix web test` 先构建再运行全部 23 项 Node 测试；`npm --prefix web run test:unit` 运行不依赖构建产物的部分。单个 Python 文件示例：`python -m unittest discover -s tests/pipeline -p "test_funding_table.py"`。

新增测试按功能放入相应目录。Python 子目录保留 `__init__.py`，确保从 `tests/` 开始发现时不会静默漏跑。
