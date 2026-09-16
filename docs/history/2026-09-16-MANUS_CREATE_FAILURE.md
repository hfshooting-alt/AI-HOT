# Manus 新闻任务创建失败诊断

## 修复后真实单源测试

用户授权后以 Lite 单次创建测试机器之心，任务 YGX6JkzdVWuiAY938VrDcp 成功创建并运行，无 400/429；使用修复后的正式新闻 schema 和北京时间 09:30 窗口。5 分钟观察上限后停止，远端已确认 stopped，任务明细和账户余额差均为 13 credits。未验证 Standard 档位或全量来源。

真实响应交付两条相邻且无换行的 AIHOT_ARTICLE JSON，旧逐行 json.loads 解析遗漏。修复为逐个完整 JSON 解码，仍要求显式前缀并逐篇校验身份、字段和时间窗口。复用保存响应，离线回收 2 篇（Vidu S2、WorldRoamBench），无新增付费。来源未核实到窗口起点，标 partial，不能称完整 24 小时覆盖。原失败台账保持不改，恢复结果留在私有 canary 的 recovered-after-parser-fix.json，尚未晋升网页。

355 项 Python 离线回归通过；后续任务可直接回收这种合并进度消息，不依赖正式 structured output 成功。

运行 35064220794：北京时间 14:33:19 至 14:33:21，20 个来源分别在创建阶段失败，前 10 个 HTTP 400（invalid_argument / unexpected error from node server），后 10 个 HTTP 429。没有返回新闻任务 ID，没有搜索中途的已核实文章可回收。独立公司资料任务稍后成功，不能将此故障归因于账户完全不可用。

代码中窗口 schema 添加 published_time_text，但未加入 required。官方要求所有属性都列入 required，即使允许 null。这是已确认的格式缺陷，与公司搜索 schema 的区别明确；服务端笼统错误不足以证明它是唯一 400 原因，仍需单源实测确认。

仅限制 3 个并发无法限制快速失败后的提交速率，20 次创建集中约 2 秒。修复为共享客户端线程锁下至少 7 秒一次，失败也占间隔；429 后冷却 60 秒再处理后续任务。不自动重新创建失败任务，不改变时间窗口、来源数量或费用止损线。其他进程共享账号请求额度，不能保证完全不再遇到 429。

新增发送前 schema 检查及回归：窗口字段完整性、非法 schema 不发送、20 个并发队列请求的失败节流和 429 冷却。本轮没有付费 API 调用；354 项 Python 离线回归通过。

官方依据：[输出结构](https://open.manus.ai/docs/v2/structured-output)、[任务创建](https://open.manus.ai/docs/v2/task.create)、[每用户请求速率](https://open.manus.ai/docs/v2/rate-limits)。
