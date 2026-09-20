# 9月19日新闻排序失败诊断与离线修复

真实运行：[35426148947](https://github.com/hfshooting-alt/AI-HOT/actions/runs/35426148947)，代码 `babc3324a807d7221a69f2c685dfb8ed58d3c209`。固定窗口为北京时间9月18日09:30至9月19日09:30。news阶段耗时0.08秒即失败，未发布。

## 已验证原因

加密Artifact `pipeline-recovery-35426148947`（ID `10579361239`）已下载、按GitHub提供的SHA256校验并解密，共141个文件。原始证据在本地 `work/audit-20260919/work/recovered/`，原state、fingerprint及所有文件校验值保持不变。

用原运行版本 `news_pipeline.py` 和保存输入零API重放，准确异常为：`candidates()` 排序调用严格的 `manus_source.window.timestamp()`，遇到合法日期精度字段 `published_at="2026-09-18"`，抛出 `ValueError: 发布时间必须含日期、时间和时区`。异常发生在相关性模型调用之前。423条AIHOT输入的发布时间均可通过该时间解析器。

触发条目为赛博禅心《从 Token-Maxxing，到 Token-Minimizing》，[腾讯新闻承载页](https://news.qq.com/rain/a/20260917A0D2PM00)。缓存保存 `publishedPrecision="date"`、原文时间标签“昨天”和观测时间 `2026-09-19T14:27:12.900760+08:00`。现有“昨天”例外允许保留日期精度，但新闻排序此前错误地假定所有条目都有完整时间。

此外，该条Manus备注明确记载正文详情显示“2026-09-17 19:04发布”，与列表“昨天”不一致。此处仅确认保存的Manus证据存在明确冲突；本次未重新打开原文核验，也未凭URL路径日期判断发布时间。冲突条目需单条隔离，不能用相对时间覆盖已知冲突。

## 修复边界

- 日期精度只在排序时使用内部日期键，原 `publishedAt`、`publishedPrecision` 和时间证据保持；严格时间戳契约未放宽。
- 新发现和旧缓存共用明确原始发布时间冲突识别。新闻入口在跨源去重前隔离冲突Manus条目，避免其正文覆盖独立AIHOT摘要；其他新闻继续处理。
- 公开隔离清单记录文章ID、标题、链接及 `original_publication_time_conflict`；原备注等证据保存到候选私有目录 `inputs/publication-time-review.json`。
- 不重跑采集，不调用付费API，不修改原失败state或正式数据。

## 真实输入及验证

该次AIHOT输入423条；Manus共20源，1个complete（FounderPark零篇）、5个partial、14个failed，发现6篇且正文6/6获取成功。成本报告余额2223降至1810，记录413 credits；18个费用止损任务均记录 `stopSucceeded=true`。以上不表示完整24小时覆盖验收通过。

保存输入经修复后的新闻入口重放，模型函数全部替换为明确的离线占位函数，并启用网络/子进程阻断。隔离上述1篇后，跨源及同源去重得到414条模型输入（409条以AIHOT为主记录、5条以Manus为主记录），完成候选feed与加工产物结构校验。414条是本次合成模型验证数量，不是实际模型审核或发布数量。

`tests/pipeline/test_combined_news.py` 的20项离线测试通过，包括日期精度端到端保留及冲突Manus与同URL AIHOT独立处理。最小脱敏夹具、原版本脚本、离线重放脚本及报告分别保存于 `work/audit-20260919/date-only-minimal-fixture.json`、`pinned_news_pipeline.py`、`replay_offline.py`、`replay-result.json`。解密的141个文件重放前后校验值全部一致。
