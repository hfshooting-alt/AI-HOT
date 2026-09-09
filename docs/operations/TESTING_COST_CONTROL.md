# 测试与成本控制

2026-09-09 用户要求：后续测试持续控制成本。默认使用离线回归；仅在必要时做最小真实调用，不能用全账号生产任务代替冒烟测试。接口失败先排错，不盲目重复创建。

## 测试入口

| 命令 | 外部调用与范围 |
| --- | --- |
| `python scripts/test_pipeline.py` | 默认 offline，运行全部 Python 测试，阻断真实网络和子进程；使用假密钥和模拟响应 |
| `python scripts/test_pipeline.py manus-auth` | 一次 GET `usage.availableCredits`，验证认证和可用 credits；不创建任务 |
| `python scripts/test_pipeline.py manus-auth --refresh` | 忽略缓存，重新做一次只读认证检查 |
| `python scripts/test_pipeline.py manus-smoke --allow-paid` | 可能收费：固定 Lite 问答，最多一次创建，不采集新闻、不发布数据 |
| `python scripts/test_pipeline.py llm-smoke --allow-paid` | 可能收费：一次 OpenAI-compatible JSON 请求，输出上限 16 token，每日最多一次 |

本地根目录 `.env` 存密钥，禁止将密钥放入 CLI 参数、日志、测试样本或 Git。`work/test-cost/` 记录认证结果、次数、任务 ID、平台返回的消费和停止状态，并已被 Git 忽略。认证成功缓存 24 小时，失败缓存 1 小时；更换密钥自动失效。命令输出 `cached`、`checkedAt` 和本次请求数，缓存余额仅代表上次检查时的余额。

`llm-smoke` 使用生产相同的 `LLM_API_BASE`、`LLM_MODEL` 和 taxonomy 密钥变量，只要求返回 `{"ok":true}`。请求发送前写入当日占位，网络超时也不重试；台账只保存模型名、结果、错误码和服务端返回的 token 用量，不保存密钥、请求全文或模型原始响应。它验证认证、模型名、`/chat/completions` 兼容性和 JSON mode，不能代表新闻摘要与分类质量。

离线入口同时用于 GitHub Actions 的 Python 测试步骤。即使业务代码吞掉网络异常，保护层仍记录拦截并使测试失败。该保护适用于此 Python 进程，是防止误调用的开发保护，不是针对恶意代码的沙箱。前端沿用本地模拟接口测试，不注入真实服务密钥。

## 最小付费问答的限制

- 需要显式 `--allow-paid`，且先查询认证与余额；余额低于 20 credits 时不创建任务。
- 当前工作区每天最多一次创建尝试，所有密钥共用本地台账；创建前先落盘占位，不做创建重试。结果未知也占用名额，避免响应丢失后重复收费。
- 固定 `lite`、固定短问答、私有任务、无附件或新闻采集输入，要求不浏览、不搜索、不写文件。不会调用 DeepSeek/Tavily 或进入生产流水线。
- 最多观察 120 秒、最多 12 次状态查询；每次 socket 请求超时 10 秒，不自动重试。清理和请求耗时可能令总墙钟时间超过 120 秒。
- 观察到任务消费达到 20 credits、需要用户输入、超时或查询失败时请求 `task.stop`。单次流程最多 18 个 HTTP 请求，包含余额、创建、状态、输出、停止和结束余额检查。
- `20 credits` 是**观察到消费后的止损阈值，不是服务端账单硬上限**。轮询间隔、消费上报延迟和停止失败都可能导致超出；任务的 `credit_usage` 缺失时记为未知，不能当作零。余额前后变化也可能包含同账号其他操作。
- 若进程强制终止或停止请求失败，远端任务可能仍运行。台账保留未解决状态，禁止后续日期继续创建；先在 Manus 通过记录的任务 ID 确认/停止原任务，再把本地记录标为已解决。不要删除台账来绕过限额。残留 `probe.lock` 也必须先确认没有运行中的探针再处理。

付费探针只验证服务连接与结构化输出，不能证明 20 个账号的网页采集质量，也不能证明新闻摘要、分类和实体抽取质量。需要真实采集联调时，沿用已授权的小样本范围，事先确定任务数、样本数和观察阈值，默认保留候选产物；当前生产 `run_pipeline.py` 不受上述探针台账限制，不应拿它直接做低成本冒烟。`--no-promote` 仅控制数据发布，不限制费用。

## 本轮验证记录

本轮向 Manus 官方余额接口发送了两次只读请求，均返回 HTTP 401。第二次检查了粘贴下划线转义的另一种形式，返回 `unauthenticated`。没有创建任务，未运行付费冒烟，余额无法查询；密钥的有效性需要重新确认。真实密钥和完整响应不提交仓库。

新增保护机制使用模拟响应验证：离线联网拦截、认证缓存、未显式启用时拒绝付费、每日一次、创建超时不重试、轮询上限、消费阈值停止、停止失败阻止后续创建以及低余额保护。

依据 Manus 官方文档：[认证](https://open.manus.im/docs/v2/authentication)、[余额](https://open.manus.im/docs/v2/usage.availableCredits)、[创建任务](https://open.manus.im/docs/v2/task.create)、[任务状态与消费](https://open.manus.im/docs/v2/task.detail)、[停止任务](https://open.manus.im/docs/v2/task.stop)。
