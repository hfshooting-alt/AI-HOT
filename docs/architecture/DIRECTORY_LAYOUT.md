# 目录分工与文件溯源

所有命令均从仓库根目录执行。2026-09-08 在 `438aaef` 基础上迁移 60 个已有文件，逐文件映射见 [PATH_MIGRATION.json](PATH_MIGRATION.json)。

```text
AI-HOT/
├── app/                         网站入口与路由（框架约定）
│   ├── _components/
│   │   ├── layout/              整体布局、侧边栏、AppShell
│   │   ├── providers/           应用级数据上下文
│   │   ├── views/               五个功能页面及其交互状态
│   │   ├── news/                新闻卡片、搜索、分类与标签筛选
│   │   ├── funding/             融资公司表格
│   │   ├── reports/             日报、周报正文详情
│   │   └── shared/              跨页面图标
│   ├── _lib/
│   │   ├── data/               数据加载、上游请求、分页与归一化
│   │   ├── domain/             数据类型、分类与融资维度
│   │   └── display/            日期格式、来源识别与搜索匹配
│   └── api/                    对外 API 路由
├── config/                     分类、生产信源与候选信源配置
├── scripts/                    稳定 CLI 入口及公共流水线工具
│   ├── manus_source/           发现 → 正文 → 契约校验
│   └── funding/                输入 → 抽取 → 合并 → 补全 → 发布
├── prompts/                    Manus 提示词
├── templates/                  静态历史页、周报页模板
├── tests/
│   ├── pipeline/               Python 流水线回归测试
│   ├── frontend/               渲染与来源展示测试
│   ├── api/                    聚合接口与分页测试
│   ├── settings/               本地设置服务测试
│   └── fixtures/               固定的采集与正文样本
├── docs/                       使用、架构、运维、参考和历史文档
├── data/                       Manus/融资数据、缓存与状态
├── archive/                    每日归档 JSON（快照构建输入）
├── public/                     网站公开静态资源与已发布快照
├── eval/                       分类人工标注与评测样本
├── build/                      Sites Vite 插件源码
├── worker/、db/、drizzle/        Cloudflare Worker 与数据库脚手架
├── examples/                   可选 D1 示例
└── .github/、.openai/            自动任务与托管配置
```

`build/` 中的 `sites-vite-plugin.ts` 是构建工具源码。`dist/`、`node_modules/`、`.vinext/`、`.wrangler/`、`__pycache__/` 是本地生成目录，已由忽略规则排除；不要在其中维护业务代码。

## 路径边界

- 框架配置、包管理器锁文件和 `.env` 保留在根目录；密钥仍保存在被忽略的 `.env` 中。
- `scripts/*.py` 和 Manus CLI 原路径保留，原有默认运行命令继续有效。
- 三个业务配置移动到 `config/`；代码默认值、测试和文档均已更新。自行写过显式参数的命令应将 `--taxonomy taxonomy.json` 改为 `--taxonomy config/taxonomy.json`，将 `--sources manus_sources.json` 改为 `--sources config/manus_sources.json`；自定义 `MANUS_SOURCES_PATH` 同理。自定义绝对路径继续按原逻辑使用。
- `tag_cache.json` 保留原位置，维持已有增量缓存；数据文件和 `public/history/`、`public/weekly/` 等公开 URL 不迁移。
- Python 测试仍可通过 `python -m unittest discover -s tests -p "test_*.py"` 递归发现全部用例。Node 测试路径已在 `package.json` 更新。

## 查找与溯源

1. 从本页或 [代码维护导航](CODEBASE_GUIDE.md) 找到功能所属目录。
2. 每个目录的 README 提供入口与依赖方向；新文件放到对应功能目录。
3. 使用 `git log --follow -- <新路径>` 查看单文件迁移前后的提交；使用 `git blame <新路径>` 查看行来源。
4. 查旧文档中的文件时，在 [迁移表](PATH_MIGRATION.json) 搜索旧路径；它记录准确的新位置和迁移基线。

不复制保留第二份业务配置或组件。新的历史计划统一放入 `docs/history/`，沿用日期开头的文件名。
