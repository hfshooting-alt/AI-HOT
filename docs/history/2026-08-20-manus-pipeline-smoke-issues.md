# Manus 采集流水线冒烟测试问题报告

> 日期：2026-08-20
> 场景：本地冒烟测试「Manus 爬取指定公众号 → DeepSeek LLM 分类 → 与 aihot 数据同屏展示」全链路
> 范围：`group_a`（5 个公众号：游戏葡萄、白鲸出海、机器之心、ZFinance、极客公园），目标日期 2026-08-19（1 天窗口）
> 结论：**发现阶段已跑通（修复前），正文阶段暴露出 2 个真实 bug + 2 个附带问题，链路未走完**。本文所有文件修改已回退，工作区干净。

---

## 1. 链路执行结果概览

| 环节 | 脚本 | 结果 |
|------|------|------|
| API 连通 | `scripts/manus_source/client.py` | ✅ 直连 `api.manus.ai` 无需 VPN，任务创建/轮询正常 |
| 阶段 A 发现 | `runner.py --groups group_a` | ⚠️ 第 1、2 次契约校验失败（见问题 1）；第 3 次成功：3 篇文章 + 3 来源失败 |
| 阶段 B 正文 | `content_phase.py` | ❌ 第 1 次字段错位、第 2 次占位文本（见问题 2）；第 3 次返回真实正文但 1 篇被误杀（见问题 3） |
| 阶段 C feed | `build_manus_feed.py` | 未执行（正文无合格结果） |
| LLM 加工 | `enrich_news.py`（DeepSeek） | 未执行 |
| 快照/前端 | `build_snapshot.py` + Next.js | 未执行 |

**发现阶段的最终结果**（2026-08-19）：

| 公众号 | 结果 |
|--------|------|
| 游戏葡萄 | ✅ 2 篇文章（《单人3个月做的AI游戏…》《游戏行业，到处都是《牛来》？》） |
| ZFinance | ✅ 1 篇文章（专访敦鸿资产俞文超） |
| 白鲸出海 | ❌ 失败：逐卡片顺序审计失败（动态重载后卡片序列无法保持） |
| 机器之心 | ❌ 失败：同上（返回列表入口后动态重载） |
| 极客公园 | ❌ 失败：同上（第 4 张卡片位置无法保持） |

---

## 2. 问题 1（P0，真实 Bug）：发现结果契约校验永远失败 —— `schema_version` 不一致

### 现象
Manus 发现任务正常完成，但返回结果在本地 `contracts.validate_discovery` 校验处必挂：

- 第 1 次：`发现结果缺少必填字段：schema_version`
- 把 `schema_version` 加进输出 schema 后重跑：`发现结果 schema_version 应为 2，实际 1`

### 根因：两侧 schema 定义不一致
| 层面 | 要求 |
|------|------|
| 发给 Manus 的 JSON Schema（`client.py` 的 `DISCOVERY_OUTPUT_SCHEMA`） | 必填：`source_group / target_date / source_audits / articles`，**没有 `schema_version`** |
| 本地契约（`contracts.validate_discovery`） | 必填：上述 4 字段 **+ `schema_version`**，且必须 **== 2** |

Manus 按它收到的 schema 输出 → 缺字段；补进 schema 后 Manus 回显 `1`（不理解该字段的项目语义，随意填值）→ 仍不等于 2。

### 为什么本地要强制 `schema_version == 2`
- v1 → v2 的演进：迁移方案（`docs/history/2026-08-17-manus-only-source-migration-plan.md` §2.1）把发现 schema 升级为 v2，**新增 `source_audits`**，从数据结构上区分「来源成功但当天无文章」（`complete + article_count=0`）与「来源采集失败」（`failed + note`）。
- 下游消费者（`build_manus_feed` → feed → `build_snapshot`）完全按 v2 结构做强校验（每账号恰好一条审计、`article_count` 与实际文章数一致等）；放行旧格式会导致这些校验无法执行。
- 契约文档（`docs/architecture/MANUS_DATA_CONTRACT.md` 版本升级规则）规定：升级 `schema_version` 时必须四件套同步——**Manus structured_output_schema、prompt 输出节、`validate_discovery`、夹具**。

### 直接原因：四件套漏了第一件
迁移到 v2 时契约/夹具/文档都改了，但 `client.py` 的 `DISCOVERY_OUTPUT_SCHEMA` **漏加 `schema_version` 字段**。

### 修复方向
`schema_version` 是 AI HOT 本地契约版本号，Manus 平台只是通用任务执行器、不理解其语义，**不应依赖 Manus 回显**。正确做法：Manus 只输出业务数据（`source_group / source_audits / articles`），`schema_version` 由本地落盘前权威补充（`runner.py` 拿到 payload 后写入 `contracts.DISCOVERY_SCHEMA_VERSION` 再校验）。校验端保持强制不变。

---

## 3. 问题 2（P0，真实 Bug）：正文阶段拿不到可信正文

正文阶段同一批次任务重试 3 次，出现三种不同的失败模式：

### 模式 A：字段错位（第 1 次）
- 现象：请求 3 篇，Manus 只返回 1 篇；且该条 `article_url` / 正文内容是 A 文章（游戏葡萄《单人3个月做的AI游戏…》）的，`title` 却是 B 文章（ZFinance 专访）的。
- 拦截点：`pipeline.py` 的「正文结果 URL 集合必须与请求清单一一对应」校验 → `ContractError: batch01 正文结果 URL 集合与请求清单不一致：缺少 [2 个 URL] 多出 []`。

### 模式 B：占位文本（第 2 次）
- 现象：3 篇齐全、URL/标题对应正确，但 `content_text` 全部是占位示例文本：

  > 已提取的正文文本，长度约4173字（示例文本，用于严格遵守输出格式和长度约束，实际文本已在内部系统完成提取与清洗）。

- 拦截点：`contracts.validate_content_batch` 的「正文过短 < 100 字符」门槛 → 3 篇全部 `failed`。
- 分析：Manus agent 在 structured output 里没有输出真实正文，用说明文字占位。原始 prompt（`prompts/manus_content.md`）虽写了 `content_text：<清洗后的可读正文>`，但**没有显式禁止占位/示例文本**，Manus 钻了空子。修复方向：prompt 增加「禁止占位」硬性约束（本 session 已试改并验证方向，后按用户要求回退）。

### 模式 C：标题空格漂移误杀（第 3 次，已拿到真实正文）
- 现象：3 篇真实正文全部返回，但第 1 篇被判失败：

  > `[failed] 游戏葡萄 …20260819A0B8ML00：正文标题与发现阶段记录不一致（跳转漂移）`

- 根因：Manus 抄写标题时多了一个空格——发现阶段标题 `…AI游戏，Steam好评率94%…`，正文批次返回 `…AI游戏， Steam好评率94%…`。本地 `norm_title` 只压缩连续空白为单空格、**不删除空格**，归一化后仍不同 → 被 `expected_titles` 一致性校验误判为「跳转漂移」。
- 影响：1 篇真实正文被误杀；说明该一致性校验对格式漂移（空格等）过严。

### 结论
- 正文阶段 schema（`pipeline.py` 的 `CONTENT_OUTPUT_SCHEMA` 与 `validate_content_batch`）**逐字段对齐，无 schema 问题**。
- 问题全在 Manus 端执行稳定性（错位 / 占位）与本地校验灵敏度（标题空格）。第 3 次（原始 prompt）能返回真实正文，说明前两次属不稳定行为，未必每次必现。

---

## 4. 问题 3（P1，附带发现）：断点续跑会把「占位批次」误判为合法结果复用

### 现象
删除占位批次前重跑 `content_phase.py`，输出：`新跑 0 批，续跑复用 1 批`——直接复用了旧占位批次，没有提交新任务，永远无法自愈。

### 根因
`pipeline.py` 的 `load_resumed_records` 只要整个批次文件通过 `validate_content_batch` 的**结构校验**（URL/标题/日期一致）就视为可复用；正文过短只是记为单条 `failed`（不抛 `ContractError`），占位批次因此被当成「合法已完成结果」。

### 修复方向
续跑复用时需区分「单条失败可重试」与「整批合法」：若批次内存在 failed 记录（正文过短/风控），不应整体复用，或至少允许按 URL 重新提交任务。

---

## 5. 问题 4（P2，附带发现）：运行 `test_build_snapshot_manus.py` 会覆盖生产文件 `public/snapshot.json`

- 现象：跑完测试后 `git status` 显示 `public/snapshot.json` 被改成夹具数据（「aihot 基础资讯一条」、`example.com` 等）。
- 根因：该测试以默认输出路径（`public/snapshot.json`）写构建产物，未隔离到临时目录。
- 影响：开发时污染前端消费数据，需 `git checkout -- public/snapshot.json` 还原。
- 修复方向：测试中显式传 `--snapshot-json` / `--out` 到临时目录。

---

## 6. 当前数据状态（work 目录，gitignore，可继续使用）

```
work/manus/2026-08-19/raw/
├── discovery-group_a.json   # 3 篇文章（游戏葡萄×2 + ZFinance×1），schema_version=2（修复后落盘）
├── discovery-group_b.json   # 本地冒烟构造的空发现（5 账号 complete+0 文章）
├── discovery-group_c.json   # 本地冒烟构造的空发现（4 账号 complete+0 文章）
└── content-batch-01.json    # 3 篇真实正文（2 篇通过校验，1 篇因标题空格漂移 failed）
```

> 注：本地只跑 group_a 冒烟时，`load_discoveries` 要求三组发现文件齐全，b/c 空发现是本地构造的合法占位（契约语义：来源成功但当天无文章）。

## 7. 未完成环节

feed 生成（`build_manus_feed.py`）、DeepSeek 正文加工（`enrich_news.py`）、快照合并（`build_snapshot.py`）、前端展示均因正文链路未闭环而未执行，待问题 1/2 修复后继续。

---

## 附：本 session 对生产代码的修改（已全部回退，工作区干净）

| 文件 | 临时修改 | 状态 |
|------|----------|------|
| `scripts/manus_source/runner.py` | 落盘前补充 `schema_version`（问题 1 修复方向验证） | 已回退 |
| `scripts/manus_source/client.py` | 输出 schema 增加 `schema_version` 字段（方向错误，Manus 回显 1） | 已回退 |
| `prompts/manus_content.md` | 新增「禁止占位」硬性约束（问题 2 修复方向验证） | 已回退 |
| `public/snapshot.json` | 被测试覆盖（问题 4） | 已 git 恢复 |
