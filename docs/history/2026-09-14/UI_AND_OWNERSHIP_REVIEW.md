# 首页整理与产品归属复核（2026-09-14）

## 已完成的修改

- 首页删除原说明段、来源状态框和融资分类入口；采集错误记录仍保留在数据和运行日志。
- 融资表格及其筛选迁入公司与产品全景；保留过期数据保护。融资新闻仍可在全部资讯阅读。
- React新闻卡片、历史页、周报和生成模板全部移除评分展示；内部字段兼容保留。
- 未具名数量集合不进入产品列表；本批法拉第未来的EAI机器人泛称也移除，保留公司和新闻。提示词v12，未将旧v11缓存改称v12。
- 官网确认产品归属时保留报道时间、原文、集成方关系，增加可点击的归属依据。

## 本轮模型与数据

7次DeepSeek-V4-Pro资料核验请求，分为5次与2次两个小批，未调用Manus。全部请求成功，输出经逐字证据验证和人工审阅；原始输入、提议和调用台账位于忽略目录work/ownership-20260914。模型提出的官网其他型号未导入。

|报道产品|归属|官方证据|
|---|---|---|
|Fable、Fable 5.1、Opus|Anthropic|https://www.anthropic.com/claude/fable ； https://www.anthropic.com/claude/opus|
|Siri|苹果|https://www.apple.com/apple-intelligence/|
|Seedance、Seedance 2.5|字节跳动|https://seed.bytedance.com/en/blog/one-take-creation-flexible-referencing-introducing-seedance-2-5|
|GPT-5.6 Sol|OpenAI|https://openai.com/index/previewing-gpt-5-6-sol/|
|Tailscale|Tailscale Inc.|https://tailscale.com/terms|
|GLM|智谱|https://z.ai/company|

候选64家公司、82项关联产品、9项待核验；199条新闻和采集诊断未改。待核验不会强行塞入正式公司产品表：commit-rewriter、CUDA-for-AMD-Windows、JAX3D、OpenClaw、Astra、Claw、Instinct、PaperRoute、Grok Bot。

JAX3D仓库明确非Google官方产品（https://github.com/google-research/jax3d）；OpenClaw由独立基金会维护（https://www.openclaw.org/），不能推断归OpenAI。Grok Bot当前官网以SpaceXAI命名，历史xAI记录与当前主体的统一仍需核对。其他为个人开发、简称歧义或证据尚不足，保留原始新闻链接。

## 自动联网补全的边界

并行科技的文本对话与API说明未找到内置联网搜索协议；当前代码也未配置搜索工具。已有Tavily适配代码但没有TAVILY_API_KEY。本次是官网检索＋DeepSeek核验，未宣称已实现每日自动联网搜索，已向用户确认搜索接口选择。

## 验证

329项Python、35项Node离线测试通过，TypeScript检查通过。正式发布使用review-candidate/publish-candidate入口，不伪造生产运行状态。部署结果另由最终回复及本地发布记录确认。
