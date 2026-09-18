# 加密恢复云端演练验收

运行：[35325119086](https://github.com/hfshooting-alt/AI-HOT/actions/runs/35325119086)，代码a573a6d。使用固定合成数据，未采集新闻、未调用模型、未发布正式数据。

两个独立GitHub runner完成：构造已完成新闻/快照、公司组装失败的固定状态与成功模型缓存 → 使用仓库现有Secret派生密钥加密 → 上传Artifact → 新runner下载 → 解密校验 → 公司与融资缓存重建 → 真实candidate发布前校验。

北京时间2026-09-18 16:35:41，verify日志返回：

- status=passed；paidCalls=0。
- 2条合成新闻，1家公司、1个产品、1条融资记录。
- 新闻窗口为北京时间9月17日09:30至18日09:30。
- realCandidateValidation=true：未mock发布前验证器。
- missingCacheBlocked=true：清除一项模型缓存后停止，不补发请求。
- tamperedBundleBlocked=true：密文损坏被拒绝。
- originalFailureStatePreserved=true：没有修改原失败state或fingerprint。
- published=false、productionDataUnchanged=true：未执行正式发布，仓库数据目录的校验值一致。

加密Artifact：synthetic-recovery-35325119086，ID10538252410。脱敏验收报告：recovery-rehearsal-report-35325119086，ID10538636954。均保留7天；长期证据为工作流日志及本记录。

本次确认了跨runner保存/下载/恢复和真实候选校验链路，不等于今日失败新闻已经恢复，不等于Manus来源全部通过，也不解决09:30触发延迟。今日旧运行没有完整模型缓存，不能借此演练补回。后续恢复真实数据应复用已有采集结果，先明确缺少的模型加工范围与调用上限。
