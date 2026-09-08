# Manus Discovery Prompt 最小增强设计

## 背景

2026-08-26 与 2026-08-27 的 `group_a` 冒烟测试中，Manus 已在一小时轮询窗口内返回结构化结果，但出现两类业务一致性问题：

- `source_audits[].article_count` 与最终 `articles` 中同账号的 `complete` 文章数不一致。
- `account_name` 留空，同时公众号名称被写入 `source_platform`。

本地 `contracts.validate_discovery` 已正确拦截这些结果。当前改进只降低 Manus 生成上述错误的概率，不调整本地契约和调用链。

## 目标

1. 只修改现有 `prompts/manus_discovery.md`。
2. 保持 `runner.py`、`client.py`、`config.py` 和工作流不变。
3. 保持 CLI、任务创建方式、structured output schema 和 discovery JSON 结构不变。
4. 在 Prompt 中明确字段映射、最终计数和提交前自检要求。
5. 继续由现有本地契约作为最终安全门禁。

## 非目标

- 不增加自动重试。
- 不修改 Manus structured output schema。
- 不增加环境变量或 CLI 参数。
- 不修改或放宽 `contracts.validate_discovery`。
- 不在本地自动修补 Manus 返回字段。
- 不调整阶段 B、阶段 C 或 feed 结构。

## Prompt 改动

在 `prompts/manus_discovery.md` 的“最终回答”之前增加“提交前强制自检”章节，并强化现有字段说明。

### 1. 来源字段是配置常量

要求 Manus 在处理每个来源时保存 Prompt 中对应的三项配置值：

```text
account_name = 公众号名称
source_platform = 平台
source_home_url = url
```

输出文章时必须逐字复制这三项配置值。页面显示的媒体名、站点名、域名或栏目名不能替代配置值。

针对已观察到的错误，Prompt 明确加入示例：

```text
公众号名称：白鲸出海
平台：Official Baijing
url：https://www.baijing.cn/article/

正确：
account_name = 白鲸出海
source_platform = Official Baijing
source_home_url = https://www.baijing.cn/article/

错误：
account_name = null
source_platform = 白鲸出海
source_home_url = https://www.baijing.cn/
```

### 2. Complete 文章字段门槛

每条 `extraction_status=complete` 的文章在最终输出前必须确认：

- `account_name` 非空，并且等于当前来源配置的公众号名称。
- `source_platform` 等于当前来源配置的平台。
- `source_home_url` 等于当前来源配置的原始 URL。
- `article_url`、`title` 非空。
- `published_date` 等于 `target_date`。

任何一项无法确认时，不允许输出为 `complete`。来源应按既有协议进入 `failed` 审计并说明原因。

### 3. 最终计数重算

要求 Manus 先完成最终 `articles` 数组，再逐账号重新计算 `article_count`：

```text
article_count = 最终 articles 中 account_name 等于该账号且 extraction_status=complete 的记录数
```

禁止沿用浏览过程中的候选数、初始发现数或排除前数量。输出前必须逐账号比较审计计数与最终数组，任何不一致都要先修正结果。

### 4. 审计完整性

提交前确认：

- 当前分组的每个配置账号在 `source_audits` 中恰好出现一次。
- `failed` 来源的 `article_count` 为 0，并带非空 `note`。
- `complete` 且当天无文章的来源使用 `article_count=0`，`note` 写“当天无文章”。
- 不得输出未配置账号。

### 5. 最终格式检查

提交前最后检查：

- 根对象只包含 `source_group`、`target_date`、`source_audits`、`articles`。
- 每个对象只包含现有契约规定的字段。
- 使用 JSON `null`，不以空字符串代替未知值。
- 最终回答只含 JSON，不包含 Markdown 代码围栏、解释或执行过程。

## 兼容性

以下内容保持原样：

- 命令：`python scripts/manus_source/runner.py --date <date> --groups <groups...>`。
- `ManusClient.create_crawl_task` 调用方式。
- `DISCOVERY_OUTPUT_SCHEMA`。
- discovery JSON 字段和文件路径。
- 本地契约校验和失败退出行为。
- 阶段 B、阶段 C 的输入输出。

## 文件改动范围

- 修改：`prompts/manus_discovery.md`
  - 增加来源字段常量、白鲸出海字段映射示例、最终计数重算和提交前自检。
- 修改：`tests/pipeline/test_manus_runner.py`
  - 增加 Prompt 渲染测试，确认强化规则存在且 `{{SOURCES}}` 仍被正确替换。

不修改其他生产脚本。

## 测试策略

1. 新增离线测试，读取并渲染真实 discovery Prompt。
2. 断言渲染结果包含 `account_name`、`source_platform`、`source_home_url` 的常量映射要求。
3. 断言渲染结果包含最终 `article_count` 重算要求。
4. 断言渲染结果包含白鲸出海的正确与错误字段映射示例。
5. 断言 `{{SOURCES}}` 占位符被替换，来源配置仍完整渲染。
6. 运行现有 Python 全量测试和 HTML 渲染测试。

## 成功标准

- 生产代码调用方式保持不变。
- Manus 最终回答前获得明确、可逐项执行的字段和计数检查规则。
- 26 号数量不一致与 27 号账号字段错位两类问题均被 Prompt 明确覆盖。
- 本地契约继续拒绝任何不合格结果。
