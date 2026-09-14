# 官网资料补全与基金会主体

## 已审核更新

|主体|国家|成立时间|官网证据|
|---|---|---|---|
|Cohere|加拿大|未新增|[官方隐私说明](https://cohere.com/applicant-privacy)，明确总部国家|
|Bending Spoons|意大利|未新增|[主体说明](https://bendingspoons.com/documents/Information%20for%20Law%20Enforcement%20Authorities.pdf)，明确S.p.A.注册国，不外推至其美国子公司|
|NVIDIA／英伟达|美国|1993年4月|[投资者FAQ](https://investor.nvidia.com/investor-resources/faqs/)，1998年为重新注册，不作为创立时间|
|IBM|美国|1911年6月16日|[投资者FAQ](https://www.ibm.com/investor/help/general-faqs)，1924年更名不作为创立时间|
|OpenClaw Foundation|美国|未新增|[项目官网](https://openclaw.ai/)，独立非营利基金会，赞助不构成所有权|

用户已确认允许基金会／开源组织主体。OpenClaw从待核实移至OpenClaw Foundation，表格、卡片及详情显示“基金会”；对应产品关系显示“维护”。后端保留类型证据，后续新闻抽取或重放后恢复审核类型。其既有报道日期及原文链接保留，不将核验日作为新新闻日期。

当前NVIDIA和英伟达为两条历史记录，本次同步补证，未合并新闻或其他字段。公司字段5条既有记录得到补全，新增1条基金会主体；总计65个主体，8项待核实，缺国家记录42降为37。新闻仍199条。

## 验证与费用

助手直接检索官方页面，再交DeepSeek-V4-Pro做逐字引文校验及人工审阅；并非模型原生联网。5次DeepSeek全部返回合格结构，报告3013 tokens，无Manus或模型搜索调用。

候选仅应用本轮审核规则，避免重放历史规则附带改变旧产品列表。所有旧主体的产品列表、报道日期保持；OpenClaw只迁移归属及主体类型。原始网页、模型响应、审核候选位于work/official-research-20260914，不提交Git。

334项Python、36项Node测试及TypeScript检查通过。正式发布通过review-candidate/publish-candidate入口；上线结果以部署验证为准。

897196b对应Pages运行34832737845已成功，线上JSON与审核数据一致。浏览器旧HTTP缓存仍可能保留上一批，因此数据读取增加cache:no-cache，在页面重新加载时验证最新JSON；跨视图的内存复用保持。

## 尚待完成

剩余37条缺国家记录继续逐项补证；8项待归属产品不猜测主体。Grok Bot涉及现有xAI名称与当前服务法人关系，需单独核对；Tailscale条款按账户日期区分加拿大与美国法人，不能把局部条款外推到整个产品。每日任务仍未接入可靠的自动搜索通道，本次为经助手核验的资料更新。
