# 2026-09-20 真实定时运行复核

本记录只描述原云端运行及其只读审计，不把随后本地恢复候选或修复代码算作该次运行结果。审计未创建、继续或重试 Manus 任务，未请求 LLM，未改正式数据。

## 运行与证据

- [定时运行 35494800781](https://github.com/hfshooting-alt/AI-HOT/actions/runs/35494800781) 的全部阶段与上传步骤成功；运行代码为 `babc3324a807d7221a69f2c685dfb8ed58d3c209`，正式数据经 rebase 推送为 `75bde95`。
- [Pages 35496514366](https://github.com/hfshooting-alt/AI-HOT/actions/runs/35496514366) 的 build、deploy 均成功。恢复包 `snapshot.json` 与从 `75bde95` 提取的候选快照字节一致，SHA-256 为 `1fcffc89b49f0faf45ba3a91828c859953b5e809d5d038932a8656967e3a7559`。
- GitHub 于北京时间 **14:39:36** 创建 schedule，较 09:30 晚 **309.6 分钟**。采集窗口仍为 `[2026-09-19 09:30, 2026-09-20 09:30)`，Asia/Shanghai；成功运行不能据此称为准点执行。
- 加密 artifact `10601220654` 共 18,019,148 bytes；下载 SHA-256 `0892e752d005475d443708b9d55ca9a2fcdeaf8dee1d71e3e60c17dbaccb8269` 与 GitHub 元数据一致。恢复 API 校验全部 246 个文件路径与摘要后解密到独立审计目录。
- 私有证据位于 `work/audit-20260920-cloud/`：`job.log`、`github-metadata.json`、`unpack-result.json`、`task-audit.json`、`task-summary.json`、`article-audit.json`、`tasks/*`。恢复根为 `work/recovered/b8c67729878a49b5858d6f3994c1e9d2/`；运行子目录为 `work/runs/2026-09-20/ten-am/5b0fc3a3229849e5b73a7312ee782307/`。密钥、签名链接与正文不写入本记录。

## Manus 来源、费用与停止

20 个发现任务全部实际创建；按原始消息的开始/停止毫秒时间回放，峰值并发 **3**、最后活跃数 **0**。只读读取各任务 detail 与完整消息页，20 个当前远端终态均为 `stopped`，均 `has_more=false`。旧诊断只有 `stopSucceeded=true`，本次“已停”结论以额外读取的真实远端终态为依据。

| 来源 | 本地来源状态 | 保留篇数 | 最终 credits |
|---|---|---:|---:|
| 游戏葡萄 | failed | 0 | 20 |
| 白鲸出海 | failed | 0 | 21 |
| 机器之心 | failed | 0 | 22 |
| ZFinance | partial | 1 | 20 |
| 极客公园 | failed | 0 | 25 |
| 东西文娱 | complete | 0 | 13 |
| 娱乐资本论 | failed | 0 | 22 |
| FounderPark | failed | 0 | 20 |
| 瑞恩资本 | failed | 0 | 22 |
| DeepTech深科技 | partial | 2 | 23 |
| ZPotential | failed | 0 | 21 |
| 华尔街见闻 | failed | 0 | 23 |
| 量子位 | failed | 0 | 20 |
| 智东西 | failed | 0 | 20 |
| 十字路口Crossing | partial | 1 | 21 |
| 投资界 | failed | 0 | 20 |
| 赛博禅心 | failed | 0 | 21 |
| elsewhere别处发生 | failed | 0 | 20 |
| 新智元 | failed | 0 | 20 |
| 硅星人 | complete | 2 | 17 |

合计 **2 complete、3 partial、15 failed**。18 个来源触及观察止损，其中 3 个已逐篇回收部分结果。新闻发现逐任务最终费用合计 **411 credits**，与余额 **1810 → 1399** 完全相符；单源 20 是观察阈值，实际最高 25，不能称硬上限。正文使用脚本完成 4+2 两批，没有正文 Manus 付费任务。

另有公司资料发现 VAST：任务 `f5Hy2mpVdFsJ7LonvhoRSS`，远端 `stopped`、**3 credits**。该次运行可归属的全部 Manus 费用合计 **414 credits**，公司任务不包含在发现阶段的 411 中。

“complete”是本轮收回的契约状态。审计确认四个来源取得窗口内样本，没有独立重新浏览每个列表及分页边界；尤其不能把两条 complete、某条正文可读或整体流水线成功描述为“20 来源全部通过/完整 24 小时覆盖”。失败来源的最后消息大多缺少足以定位页面问题的证据，无法将它们全部归因为入口不可达。

## 实际输入与输出

从原始任务 user message 的附件读取了全部 20 份真实 prompt。**19/19 个非机器之心来源均含 `Official Jiqizhixin` 和“机器之心详情正文由浏览器渲染”两段专属指令**，与旧 `babc3324` 的输入污染一致。FounderPark 任务 `o5XqZMuVtgPKq44ySdvdqj` 的来源列表仅一个，进度消息却称“已确认采集范围为两个配置来源”。这是本次真实范围偏移证据；它不能证明其余失败均由污染导致。

全部 prompt 已包含固定窗口、原始发布/发送时间、互动/编辑不刷新窗口、“昨天”例外及逐篇 `AIHOT_ARTICLE` 交付规则。6 条被保留结果均提供窗口内绝对时间，没有使用“昨天”例外；未发现 Sep19 已知的绝对时间与相对标签冲突样式。以 09:30 运行配置离线重验，6/6 通过当前身份与时间契约。

以下 6 篇正文均 `content_status=complete`、`content_truncated=false`，全部进入当日 238 条发布快照。正文 SHA-256 与发布记录逐条一致，完整正文也逐条保留在 `inputs/company-evidence.json`；这不代表下游模型提示词没有自身输入长度上限。

| 来源 / 标题 | articleID | 正文字符数 | 原始云公司抽取 |
|---|---|---:|---|
| ZFinance：Z Waves｜专访 Panda AI 李昱琦：用 Harness 重构投研，做交易领域的 Claude Code | `manus:1e0729fbc348ed39` | 17035 | complete |
| DeepTech：Anthropic秘密建立湿实验室，野心指向药物研发全链条 | `manus:5f886e0af76708db` | 2807 | complete |
| DeepTech：Cell重磅：把血液、基因和蛋白数据交给AI，它开始学会判断衰老 | `manus:94df7155197fc930` | 3614 | failed |
| Crossing：YC最新投资的236家公司：“几乎所有事情都不一样了” | `manus:6f00ffd05c21da7d` | 3422 | failed |
| 硅星人：Anthropic之恶 | `manus:d7f8c6a3a46e7e95` | 5415 | failed |
| 硅星人：最后两周！AI大咖、明星Founder与VC齐聚旧金山，免费票限量开放 | `manus:9f4fd4c8b4b7bfa8` | 5174 | failed |

统一新闻流程记录 276 个候选、238 条发布、26 条排除、12 条隔离，`collectionStatus.degraded=true`。238 条含 232 条 AIHOT 和上述 6 条 Manus；新闻发布成功与公司抽取成功是不同状态。

## 公司、融资与诊断限制

公司抽取 238 次、234 complete、4 failed；原成功缓存保留完整结果，不含这 4 篇失败响应原文。公司阶段恰有 4 条 `operation=unspecified` 用量记录的 `completion_tokens=1024`，分别在 UTC 07:10:47、07:12:51、07:15:52、07:15:53。旧代码没有阶段显式 `max_tokens`，使用全局 1024 上限，因此有明确输出容量不足迹象；**旧账本没有 articleID、finish_reason 或原始模型响应，不能逐条证明这 4 次就是上述 4 篇，也不能把推断写成已确认的截断错误**。后续 6144 容量及新版 prompt 的补抽属于独立恢复候选。

原融资阶段 29 篇：25 缓存命中、4 新抽取、0 失败、2 无融资信息；公司表 21 家。该运行 LLM 用量账本共 753 条：266 relevance_screen、240 news_enrichment、242 unspecified（238 公司、4 融资阶段）、5 company_research；累计输入 851,133、输出 88,078、总计 939,211 tokens。账本未保存货币金额，不能换算成已核实人民币费用。

VAST 资料发现有一项独立解析缺陷：原进度消息把 4 个真实 URL 用反引号和顿号分隔，旧提取器把整串当成一个 URL，进入 `companyDiscovery.last.urls[0]` 及 `companyDiscovery.history['company:375eca5944bc3c25'].urls[0]`。实际四链接依次为 Tripo research、Sony/VAST 合作博客、SCMP Tripo 报道、VAST GitHub；不能把拼接串当成已读页面或据此补资料。本次后续代码修复统一分拆显式链接，再逐条校验，仍保留 HTTPS 限制、下游公开页读取验证及报告最多 3 条；3 个新增回归加既有 7 个测试共 **10/10 通过，离线网络/子进程违规 0**。没有为此重新抓页面或调用模型。

本轮最新 Manus 输入隔离、停止终态确认及抽取容量修复均尚未被这次旧代码云运行验证；需以之后运行的实际证据验收，不能用离线通过代替真实来源覆盖。
