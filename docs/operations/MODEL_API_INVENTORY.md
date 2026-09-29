# 当前模型与API清单

核对日期：2026-09-29。依据实际代码、当前本地配置、GitHub工作流和当天已完成的运行；不展示密钥，不进行新的付费测试。

## 正式管线唯一启用的模型API

| 项目 | 配置 |
| --- | --- |
| 服务商 | 并行科技 Paratera |
| 模型ID | `DeepSeek-V4-Pro` |
| API Base | `https://llmapi.paratera.com/v1` |
| 生成接口 | `POST /chat/completions`，OpenAI兼容格式 |
| 鉴权 | `Authorization: Bearer <key>` |
| GitHub Secret | `PARATERA_API_KEY` |
| 本地当前密钥变量 | `DEEPSEEK_API_KEY`，兼容别名，实际请求仍发并行科技 |
| 本地推荐变量 | `PARATERA_API_KEY`；仅在并行科技域名优先使用 |
| 模型与地址变量 | `LLM_MODEL`、`LLM_API_BASE`；本地可覆盖，GitHub手动生产固定上述值 |
| 公共调用实现 | `scripts/llm_common.py` 的 `call_llm` |
| 默认配置 | `config/taxonomy.json` 的 `model` |
| 本地配置样例 | `config/env.example`；真实项目根 `.env` 不入Git |

同一个API负责：文章AI相关性筛选、全部合格正文摘要与分类、精选文章公司／产品抽取、融资信息抽取、已知网页材料的公司资料补全。不是六套API，也不需要六把key。9月29日真实运行使用该模型完成新闻和公司加工，但仍有单篇输出截断/分类失败，不能把批次成功解释成所有请求成功。

网页列表和正文由代码匿名HTTP读取，不调用模型搜索。公司资料补全先读取已知URL，再让DeepSeek从网页文本提取字段；当前没有启用通用联网搜索接口。只有具备原文证据的字段才可以作为补全结果，模型知识不是搜索证据。

## 停用及兼容项

| 服务／模型 | 当前状态 | 保留用途 |
| --- | --- | --- |
| Manus（历史`manus-1.6` / `manus-1.6-lite`） | `config/services.json`中false，生产采集与公司寻链不调用；本地存在旧key | 历史代码、证据回放；旧key也可能参与恢复包解密回退 |
| DeepSeek官方API、旧`deepseek-v4-flash` | 当前生产不调用，也没有自动回退 | 历史配置／测试记录；当前名为DEEPSEEK_API_KEY的本地变量不能据名字认定为官方key |
| GLM-4V、Baichuan-M3等历史联网试验 | 未接入当前正式管线 | 历史测试记录，不代表生产已启用联网搜索 |
| Tavily | 服务开关false，本地未配置key | 历史搜索实现；不是大模型API |
| AIHOT | 已退役、不采集 | 历史兼容代码和旧记录；不是大模型API |

`check-api-config.yml`是保留的只读诊断工作流：读取Paratera `/models`，并有旧Manus余额检查逻辑；手动触发或该文件变更才执行，不属于日常生产模型调用。本次没有触发它，没有复测旧密钥。服务开关关闭时Manus客户端仍须遵守服务门禁。

## 其他凭证，不是模型API

- `PIPELINE_RECOVERY_KEY`：恢复包加密／解密。工作流兼容回退顺序为该变量 → PARATERA_API_KEY → DEEPSEEK_API_KEY → MANUS_API_KEY。本地当前未单独配置它。停用模型不等于旧恢复包不再需要对应解密凭证，所以本次没有删除旧key。
- `GITHUB_TOKEN`：GitHub运行中提交数据、上传产物和触发Pages；不是付费模型。
- GitHub Secret的值不可读回。本清单核实了工作流引用与当天成功调用，本次未声称逐一读取或验证所有远端Secrets。

## 定时状态

用户2026-09-29要求取消全部定时：`.github/workflows/fetch-manus.yml`不再声明schedule；Codex `ai-hot`自动跟进已删除。保留手动Run workflow、提交触发的离线CI与Pages。此次不触发新的新闻采集或付费模型任务，也未建立双表数据库每周同步任务。
