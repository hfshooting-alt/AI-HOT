# 业务配置

| 文件 | 职责 | 读取入口 |
| --- | --- | --- |
| `manus_sources.json` | 生产采集账号和三组分工 | `scripts/manus_source/config.py`、`build_manus_feed.py` |
| `taxonomy.json` | 分类、维度、模型、摘要和融资抽取参数 | `scripts/tag_news.py` 及各流水线 CLI |
| `accounts.json` | 扩容候选账号池 | 人工维护，当前生产采集读取 Manus 配置 |

这三个文件从根目录原样迁入，内容未改。配置中不存 API Key；密钥使用根目录 `.env` 或环境变量。改 taxonomy 时同时检查前端 `web/app/_lib/domain/` 中的展示枚举，并运行流水线回归测试。
