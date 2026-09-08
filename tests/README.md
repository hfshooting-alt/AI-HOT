# 测试入口

| 目录 | 内容 | 执行方式 |
| --- | --- | --- |
| `pipeline/` | 169 项 Python 流水线测试 | `python -m unittest discover -s tests -p "test_*.py"` |
| `frontend/` | SSR 与来源/搜索展示 | 包含在 `npm test` |
| `api/` | 分页边界与构建后的接口响应 | 包含在 `npm test` |
| `settings/` | 设置服务、文件保存、CORS | 包含在 `npm test` |
| `fixtures/` | Manus JSON 与正文 HTML 样本 | 由流水线测试读取 |

`npm test` 先构建再运行全部 23 项 Node 测试；`npm run test:unit` 运行不依赖构建产物的部分。单个 Python 文件示例：`python -m unittest discover -s tests/pipeline -p "test_funding_table.py"`。

新增测试按功能放入相应目录。Python 子目录保留 `__init__.py`，确保从 `tests/` 开始发现时不会静默漏跑。
