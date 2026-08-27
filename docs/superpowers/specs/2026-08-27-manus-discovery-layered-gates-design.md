# Manus Discovery 分层门禁设计

## 背景

2026-08-25 至 2026-08-27 的 `group_a` 冒烟测试证明 Manus 任务可以在一小时轮询窗口内返回，但部分结构化结果未满足本地数据契约：

- 审计记录的 `article_count` 与最终 `complete` 文章数不一致。
- `account_name` 留空，同时公众号名称被写入 `source_platform`。
- 个别来源因动态重载或顺序索引重复而无法完成顺序审计。

现有本地契约成功阻止了异常结果落盘。改进目标是降低 Manus 产生异常结果的概率，并在偶发契约失败时提供一次有边界的自动恢复机会。

## 目标

1. 保持现有 CLI：`python scripts/manus_source/runner.py --date <date> --groups <groups...>`。
2. 保持 discovery JSON 的根字段、审计字段和文章字段不变。
3. 保持阶段 A、B、C 的调用顺序和文件路径不变。
4. 在 Prompt、Manus structured output schema、本地契约三层形成递进门禁。
5. 首次结构化结果违反本地契约时，最多重新创建一次同组 Manus 任务。
6. 第二次仍失败时维持现有安全语义：不写 discovery 文件，不进入正文阶段，不晋升 feed。

## 非目标

- 不改变 `data/manus/current.json` 的 feed 契约。
- 不放宽现有 `contracts.validate_discovery` 校验。
- 不静默修补 `account_name`、文章数量、日期或 URL。
- 不恢复 WeRead、搜狗或其他旧信源链路。
- 不改变阶段 B 的正文提取模式。

## 方案概览

采用四层防护：

1. **Prompt 门禁**：明确来源字段是配置常量，并要求提交前重新计算统计。
2. **Schema 门禁**：按当前任务动态生成 schema，以枚举和常量限制分组、日期、账号、平台和主页 URL。
3. **契约门禁**：继续使用本地严格契约检查跨字段和跨数组一致性。
4. **恢复门禁**：仅在契约失败时创建一次新任务，并把首轮错误反馈给 Manus。

## 兼容性约束

### CLI

现有参数和默认值保持不变。新增重试配置通过环境变量控制，不增加必填 CLI 参数：

```text
MANUS_DISCOVERY_CONTRACT_RETRIES=1
```

默认值为 `1`，允许设置为 `0` 关闭契约重试。配置必须是非负整数。

### 输出结构

合法 discovery 结果继续写入：

```text
work/manus/<date>/raw/discovery-<group>.json
```

文件结构继续使用：

```text
source_group
target_date
schema_version
source_audits[]
articles[]
```

重试次数、首轮错误和任务 URL只输出到运行日志，不写入 discovery JSON，避免改变消费者契约。

## Prompt 门禁

在 `prompts/manus_discovery.md` 的最终回答前增加“提交前强制自检”。自检要求：

1. 对每个配置来源建立不可变映射：
   - `account_name` 必须逐字复制配置中的公众号名称。
   - `source_platform` 必须逐字复制配置中的平台名称。
   - `source_home_url` 必须逐字复制配置中的原始 URL。
2. `complete` 文章的 `account_name`、`source_platform`、`source_home_url` 禁止为 `null` 或空字符串。
3. `article_count` 必须在最终 `articles` 数组完成后重新计算，只统计同账号且 `extraction_status=complete` 的记录。
4. 每个配置账号必须在 `source_audits` 中恰好出现一次。
5. 最终输出前检查根字段和对象字段，禁止 Markdown、解释文字和额外字段。
6. 若证据不足，来源应进入 `failed` 审计并附原因，不允许补写或猜测文章。

重试任务的简报额外包含首轮契约错误，例如数量不一致或账号为空，并要求从来源配置重新生成完整结果。错误文本仅用于指导重试，不改变 Prompt 模板的结构。

## Schema 门禁

在 `scripts/manus_source/client.py` 中保留现有 `DISCOVERY_OUTPUT_SCHEMA` 作为基础 schema，并新增一个纯函数，按任务参数生成深拷贝后的 schema。调用方仍通过 `create_crawl_task(..., output_schema=...)` 传入。

动态约束包括：

- `source_group`：只允许当前 group。
- `target_date`：只允许当前日期。
- `source_audits[].account_name`：只允许当前组配置账号。
- `source_audits[].article_count`：整数且不小于 0。
- `articles[].account_name`：只允许当前组配置账号或 `null`。
- `articles[].source_platform`：只允许当前组配置平台或 `null`。
- `articles[].source_home_url`：只允许当前组原始主页 URL 或 `null`。
- `articles[].published_date`：只允许当前目标日期或 `null`。

采用 Manus 当前已使用的基础 JSON Schema 能力：`enum`、`minimum`、`description` 和 `additionalProperties=false`。跨数组计数一致性、账号与平台配对关系继续交给本地契约处理，避免依赖 Manus 可能不支持的复杂条件 schema。

## 契约失败重试

`run_discovery` 增加有限循环，总尝试次数为：

```text
1 + discovery_contract_retries
```

每次尝试都执行完整流程：

1. 创建新的 Manus discovery 任务。
2. 等待 structured output。
3. 本地补充 `schema_version`。
4. 调用 `contracts.validate_discovery`。

处理规则：

- 首次通过：立即返回，不创建第二个任务。
- 首次抛出 `contracts.ContractError`：记录错误与任务 URL，创建一次重试任务。
- 第二次通过：返回第二次合法结果。
- 第二次仍为 `ContractError`：抛出包含两次错误摘要的最终异常。
- API 连接错误、Manus 终态错误和一小时任务超时：沿用现有客户端行为，不触发契约重试。

重试任务标题增加“契约重试 1/1”，日志明确显示尝试序号，便于追踪成本。

## 安全与数据真实性

- 本地代码不根据 `source_platform` 或 URL 推断并填充 `account_name`。
- 本地代码不修改 Manus 返回的 `article_count`。
- 本地代码不把 URL 中的日期当成发布日事实来源。
- 只有完整通过本地契约的 payload 才能写入 `raw` 目录。
- 首轮非法 payload 不落盘，日志仅记录契约错误和任务 URL，不输出 API Key。

## 文件改动范围

- `scripts/manus_source/config.py`
  - 新增 `discovery_contract_retries` 配置，默认 1。
- `scripts/manus_source/client.py`
  - 新增任务级 discovery schema 构造函数。
- `scripts/manus_source/runner.py`
  - 使用动态 schema；契约失败后最多重试一次。
- `prompts/manus_discovery.md`
  - 增加提交前强制自检和字段常量规则。
- `tests/test_manus_client.py`
  - 覆盖动态 schema 的枚举、日期和非负计数限制。
- `tests/test_manus_runner.py`
  - 覆盖首次成功、重试成功、两次失败和不对 API/超时错误做契约重试。
- `.env.example`
  - 记录 `MANUS_DISCOVERY_CONTRACT_RETRIES=1`。
- `docs/MANUS_SOURCE_RUNBOOK.md` 及项目要求的流水线交接文档
  - 同步重试语义、成本上限、故障排查和配置项。

## 测试策略

测试全程离线，不调用真实 Manus API。

1. 动态 schema：当前 group、日期、账号、平台和主页 URL 被正确写入约束。
2. 首轮合法：只创建一次任务，返回结构保持不变。
3. 首轮契约失败、次轮合法：创建两次任务，第二次简报包含首轮错误。
4. 两轮契约失败：最终失败，不返回非法 payload。
5. API 错误和超时：不进入契约重试循环。
6. 配置解析：默认值为 1，环境变量 0 可关闭，负数被拒绝。
7. Prompt：包含字段常量、自检统计和禁止猜测要求。
8. 全量 Python、HTML 渲染与现有 Manus 契约测试保持通过。

## 成功标准

- 现有 CLI 和文件消费者无需修改。
- 合法首轮任务没有额外 Manus 成本。
- 契约失败最多额外创建一个同组任务。
- 26 号数量不一致和 27 号账号为空两类结果均能触发一次明确重试。
- 两次非法结果都不会写入 discovery 文件或生产 feed。
