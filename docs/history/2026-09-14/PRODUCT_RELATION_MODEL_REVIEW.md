# 产品关系真实样本测试（2026-09-14）

范围：6篇已采集文章；模型DeepSeek-V4-Pro，首轮6次、针对失败项复测2次，累计8次请求全部返回，服务端合计10395 tokens。没有Manus任务，没有费用金额推算。正式新闻和公司库未由本次样本替换。

| 样本 | 实测与修正 |
|---|---|
| 微软整合xAI Grok | v9漏微软/Grok且把接收集成的Word等标integrated；v10正确返回微软/Grok integrated、xAI/Grok owned |
| 特斯拉/Grok | v9返回integrated，原文证据通过 |
| Meta Muse接入Tailscale | v9及v10均保留Meta/Muse owned和Meta/Tailscale integrated，但把工具推成同名公司；v11证据门禁将该主体降为待核实产品 |
| commit-rewriter | v9保留独立产品，不创建Simon Willison公司 |
| CUDA-for-AMD-Windows | v9保留可用开源工具，不猜AMD为开发主体 |
| Recurrent Looped Transformer | v9返回空实体数组，论文新闻仍保留 |

v11沿用v10关系方向提示，增加狭义的同名集成产品身份门禁：同名产品被另一主体集成／使用，且其身份引文仅为工具／产品描述、没有公司团队开发运营等依据时，不将其当成公司，关系降为unknown并保留产品。该门禁不是公司身份的全面核验。

验证边界：4个v9样本和2个v10复测结果均经v11离线门禁；没有将旧缓存伪装v11缓存，没有进行v11模型全量重跑。样本增量重复合并幂等。326项Python、35项Node回归通过。

私有逐条结果：work/product-relations-v9、work/product-relations-v10；合并复核work/product-relations-reviewed.json；可视报告work/product-relations-review.html。原始输入仍保留在各结果中，不提交Git。

下一步：对全量既有文章进行新版抽取，重点复核待核实公司身份及历史关系替换，再通过候选审核发布；暂不因小样本通过宣称全量公司库已核实。
