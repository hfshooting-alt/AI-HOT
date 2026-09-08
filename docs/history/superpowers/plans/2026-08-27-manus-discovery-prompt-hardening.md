# Manus Discovery Prompt Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过最小化 Prompt 增补，降低 Manus discovery 返回来源字段错位、审计计数失配和不完整 JSON 的概率，同时保持现有调用链、契约及返回结构不变。

**Architecture:** 沿用 `runner.render_discovery_prompt()` 的模板读取与 `{{SOURCES}}` 替换机制，只在现有 discovery Prompt 中补充来源配置常量、complete 字段门槛、最终计数重算和提交前自检。离线测试直接渲染真实模板并锁定这些关键约束；现有 `contracts.validate_discovery` 继续承担最终契约校验。

**Tech Stack:** Python 3、标准库 `unittest`、pytest、Markdown Prompt 模板、Node.js 内置测试运行器。

---

## 实施边界与文件地图

权威工作目录：

`C:\Users\wade.liu\Downloads\Garena\AI HOT2\AI HOT\ai hot-site\aihot-site`

本计划只允许修改以下两个文件：

- Modify: `prompts/manus_discovery.md` — 在现有协议和 JSON 示例基础上补充 Manus 提交前约束。
- Modify: `tests/pipeline/test_manus_runner.py` — 保留已有 `TestRunnerTimeout`，追加真实 Prompt 渲染测试。

以下内容明确排除：

- `scripts/manus_source/runner.py`、`client.py`、`config.py`、`contracts.py` 以及其他生产脚本。
- `DISCOVERY_OUTPUT_SCHEMA`、discovery JSON 字段、字段类型和根对象结构。
- Manus 任务创建方式、轮询方式、超时、重试、环境变量、CLI 参数。
- 阶段 B、阶段 C、feed 构建与本地契约行为。
- 当前工作树中其他 agent 或用户已有的修改和未跟踪文件。

实现前先运行：

```powershell
git status --short
```

预期：工作树已有修改，其中 `scripts/manus_source/runner.py` 有用户改动，`tests/pipeline/test_manus_runner.py` 当前可能仍为未跟踪文件。记录初始状态；后续仅在指定两个文件内追加本方案内容，不清理、不覆盖其他路径。

### Task 1: 为 Prompt 强化规则建立失败测试

**Files:**

- Modify: `tests/pipeline/test_manus_runner.py`，在现有 `TestRunnerTimeout` 之后、`if __name__ == "__main__":` 之前追加测试类。
- Test: `tests/pipeline/test_manus_runner.py`

- [ ] **Step 1: 保留已有超时测试并追加真实 Prompt 渲染夹具**

在 `tests/pipeline/test_manus_runner.py` 中原样保留 `TestRunnerTimeout`，追加以下完整测试类：

```python
class TestDiscoveryPrompt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered = runner.render_discovery_prompt(
            runner.PROJECT_ROOT / "prompts" / "manus_discovery.md",
            [{
                "account_name": "白鲸出海",
                "platform": "Official Baijing",
                "home_url": "https://www.baijing.cn/article/",
            }],
        )

    def test_render_binds_article_source_fields_to_config_constants(self):
        self.assertNotIn("{{SOURCES}}", self.rendered)
        self.assertIn("公众号名称：白鲸出海", self.rendered)
        self.assertIn("url：https://www.baijing.cn/article/", self.rendered)
        self.assertIn("平台：Official Baijing", self.rendered)
        self.assertIn("account_name = 当前来源配置的公众号名称", self.rendered)
        self.assertIn("source_platform = 当前来源配置的平台", self.rendered)
        self.assertIn("source_home_url = 当前来源配置的原始 url", self.rendered)
        self.assertIn("account_name = 白鲸出海", self.rendered)
        self.assertIn("source_platform = Official Baijing", self.rendered)
        self.assertIn("source_home_url = https://www.baijing.cn/article/", self.rendered)
        self.assertIn("account_name = null", self.rendered)
        self.assertIn("source_platform = 白鲸出海", self.rendered)
        self.assertIn("source_home_url = https://www.baijing.cn/", self.rendered)

    def test_prompt_requires_complete_article_field_check(self):
        self.assertIn("每条 extraction_status=complete 的文章", self.rendered)
        self.assertIn(
            "account_name 非空，并且等于当前来源配置的公众号名称",
            self.rendered,
        )
        self.assertIn(
            "source_platform 等于当前来源配置的平台",
            self.rendered,
        )
        self.assertIn(
            "source_home_url 等于当前来源配置的原始 url",
            self.rendered,
        )
        self.assertIn("published_date 等于 target_date", self.rendered)

    def test_prompt_requires_final_recount_and_json_self_check(self):
        self.assertIn(
            "article_count = 最终 articles 中 account_name 等于该账号且 "
            "extraction_status=complete 的记录数",
            self.rendered,
        )
        self.assertIn(
            "当前分组的每个配置账号在 source_audits 中恰好出现一次",
            self.rendered,
        )
        self.assertIn(
            "failed 来源的 article_count 必须为 0，并且 note 非空",
            self.rendered,
        )
        self.assertIn(
            "根对象只包含 source_group、target_date、source_audits、articles",
            self.rendered,
        )
        self.assertIn("最终回答只含 JSON", self.rendered)
```

- [ ] **Step 2: 运行新增测试，确认当前 Prompt 尚未满足强化规则**

Run:

```powershell
python -m pytest tests/test_manus_runner.py::TestDiscoveryPrompt -q
```

Expected: `3 failed`。失败信息应为 `AssertionError`，指出当前渲染文本缺少来源配置常量、complete 字段检查或最终计数自检文案；不得出现导入错误、文件找不到或 `{{SOURCES}}` 渲染异常。

- [ ] **Step 3: 核对失败范围**

Run:

```powershell
python -m pytest tests/test_manus_runner.py::TestRunnerTimeout -q
```

Expected: `1 passed`，证明追加测试未破坏已有一小时超时行为测试。

### Task 2: 最小强化现有 Discovery Prompt

**Files:**

- Modify: `prompts/manus_discovery.md:96-153`
- Test: `tests/test_manus_runner.py::TestDiscoveryPrompt`

- [ ] **Step 1: 在输出字段章节补充来源配置常量**

在现有 `# 四、输出字段与状态` 标题后、`## source_audits` 前插入以下原文：

````markdown
## 来源配置常量

处理每个来源时，先保存本 Prompt“采集来源”中该来源的三项配置值：

```text
account_name = 当前来源配置的公众号名称
source_platform = 当前来源配置的平台
source_home_url = 当前来源配置的原始 url
```

输出 articles 时必须逐字复制这三项配置值。页面显示的媒体名、站点名、域名或栏目名不得替代配置值。

白鲸出海的字段映射示例：

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
````

此处只明确现有 `account_name`、`source_platform`、`source_home_url` 的取值来源，不新增字段。

- [ ] **Step 2: 在最终回答前加入提交前强制自检**

将现有 `# 五、最终回答` 改为 `# 六、最终回答`，并在它前面插入以下完整章节：

````markdown
# 五、提交前强制自检

先完成最终 articles 数组，再按以下顺序检查并修正结果。

## 1. complete 文章字段检查

每条 extraction_status=complete 的文章必须同时满足：

- account_name 非空，并且等于当前来源配置的公众号名称。
- source_platform 等于当前来源配置的平台。
- source_home_url 等于当前来源配置的原始 url。
- article_url 和 title 非空。
- published_date 等于 target_date。

任何一项无法确认时，该文章不得输出为 complete；该来源按既有协议写入 source_status=failed 审计并说明原因。

## 2. 最终计数重算

articles 数组确定后，逐账号重新计算：

```text
article_count = 最终 articles 中 account_name 等于该账号且 extraction_status=complete 的记录数
```

不得沿用浏览过程中的候选数、初始发现数或排除前数量。逐账号比较 source_audits 中的 article_count 与最终 articles；存在差异时，先修正结果再提交。

## 3. 审计完整性检查

- 当前分组的每个配置账号在 source_audits 中恰好出现一次。
- failed 来源的 article_count 必须为 0，并且 note 非空。
- complete 且当天无文章的来源使用 article_count=0，note 写“当天无文章”。
- 不得输出未配置账号。

## 4. 最终格式检查

- 根对象只包含 source_group、target_date、source_audits、articles。
- 每个对象只包含第四节和下方 JSON 示例规定的现有字段。
- 使用 JSON null，不以空字符串代替未知值。
- 最终回答只含 JSON，不包含 Markdown 代码围栏、解释或执行过程。
````

- [ ] **Step 3: 检查 Prompt 结构保持兼容**

人工核对 `prompts/manus_discovery.md`：

- `{{SOURCES}}` 仍只位于“二、采集来源”中。
- 原有任务边界、入口自检、日期 SSOT、顺序状态机、顺序审计和二次反查内容保持原样。
- 原有 JSON 示例字段保持原样，根对象仍为 `source_group`、`target_date`、`source_audits`、`articles`。
- 没有新增 schema、重试、CLI、环境变量或本地修补说明。

- [ ] **Step 4: 运行针对性测试，确认 Prompt 强化转绿**

Run:

```powershell
python -m pytest tests/test_manus_runner.py::TestDiscoveryPrompt -q
```

Expected: `3 passed`。

- [ ] **Step 5: 运行 runner 测试文件，确认新旧测试共存**

Run:

```powershell
python -m pytest tests/test_manus_runner.py -q
```

Expected: `4 passed`，包含 3 个 Prompt 测试与现有 1 个一小时超时测试。

### Task 3: 全量回归与改动范围核验

**Files:**

- Verify: `prompts/manus_discovery.md`
- Verify: `tests/pipeline/test_manus_runner.py`
- Verify unchanged: `scripts/manus_source/*.py` 及项目其他文件。

- [ ] **Step 1: 运行 Python 全量离线测试**

Run:

```powershell
python -m pytest tests/ -q
```

Expected: 全部测试通过，退出码为 `0`，无 failed 或 error。当前基线若为 163 个测试，新增 3 个测试后应显示约 `166 passed`；并行 agent 新增测试时以“零失败”为判断标准。

- [ ] **Step 2: 运行 HTML 渲染回归测试**

Run:

```powershell
node --test tests/frontend/rendered-html.test.mjs
```

Expected: 退出码为 `0`，现有 2 个渲染子测试均通过。

- [ ] **Step 3: 检查空白和补丁格式**

Run:

```powershell
git diff --check -- prompts/manus_discovery.md tests/test_manus_runner.py
```

Expected: 无输出，退出码为 `0`。

- [ ] **Step 4: 审查任务拥有的差异**

Run:

```powershell
git diff -- prompts/manus_discovery.md tests/test_manus_runner.py
git status --short
```

Expected: 本任务新增内容只涉及 `prompts/manus_discovery.md` 和 `tests/pipeline/test_manus_runner.py`。`TestRunnerTimeout` 保持存在且内容未被删除；初始状态中已有的 `runner.py` 和其他未跟踪文件保持原状。若 `tests/pipeline/test_manus_runner.py` 仍为未跟踪文件，使用 `Get-Content` 审阅其完整内容，避免 `git diff` 不展示未跟踪文件造成漏检。

### Task 4: 提交已验证的最小改动

**Files:**

- Stage: `prompts/manus_discovery.md`
- Stage: `tests/pipeline/test_manus_runner.py`

- [ ] **Step 1: 只暂存本任务允许的两个文件**

Run:

```powershell
git add -- prompts/manus_discovery.md tests/test_manus_runner.py
git diff --cached --name-only
```

Expected: 暂存列表只包含：

```text
prompts/manus_discovery.md
tests/test_manus_runner.py
```

如暂存列表出现其他路径，先取消这些额外路径的暂存状态，保留其工作树内容。

- [ ] **Step 2: 审查暂存补丁并提交**

Run:

```powershell
git diff --cached --check
git diff --cached
git commit -m "fix: 强化 Manus discovery Prompt 自检"
```

Expected: `git diff --cached --check` 无输出；暂存补丁只包含 Prompt 强化和对应测试；提交成功。不得暂存或提交 `scripts/manus_source/runner.py` 及其他已有工作树改动。

## 完成标准

- 三个新增 Prompt 渲染测试先红后绿，已有超时测试持续通过。
- Prompt 明确覆盖白鲸出海字段错位、complete 字段完整性、最终 `article_count` 重算、审计完整性和 JSON-only 自检。
- `{{SOURCES}}` 继续由现有渲染函数正确替换。
- Python 与 Node 全量离线测试均通过。
- 实施改动仅落在 `prompts/manus_discovery.md` 和 `tests/pipeline/test_manus_runner.py`；生产脚本、契约、schema、重试、配置和 CLI 均无新增改动。
