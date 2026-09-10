# Manus 信源运维手册（MANUS_SOURCE_RUNBOOK）

> 2026-09-08 更新。统一入口、候选产物与恢复操作详见 [自动流水线](AUTOMATED_PIPELINE.md)。本页保留 Manus 分阶段排错说明。
> 架构背景见 `../history/2026-08-17-manus-only-source-migration-plan.md`。

## 1. 日常运行（全自动）

- 定时：每天北京时间 10:00（UTC 02:00）开始；固定窗口为前一日十点至该日十点，含起点不含终点。`date` 是窗口结束日，实际启动可能因 GitHub 排队延迟。
- `fetch-manus.yml` 依次执行 discovery、content、feed、snapshot（含历史/周报）、funding，全部成功后更新正式产物并提交。
- 失败查看 Actions 日志和 `pipeline-status` Artifact；不自动发 Issue 或评论。

## 2. 手动运行与调试

### 获取能力样本（2026-09-10）

`python scripts/probe_source_capability.py --date 2026-09-10 --accounts "机器之心" --allow-paid` 只获取1篇、最多2篇样本后结束，不检查全天边界。每来源每天一次，Lite、240秒、20 credits观察止损线、创建不重试、并发2。输出在 `work/source-capability/<date>/`。`capability` 表示文章/发布者/精确时间样本可取得；`sampleWindowVerified` 单独验证固定窗口；`coverage` 保留 unconfirmed。时间越窗样本可证明访问能力，但不进入该窗口新闻。旧任务仅有进度叙述时明确标注证据级别，不伪造成结构化样本。

Actions 页 → `AI HOT 每日采集与完整数据更新` → Run workflow：

| 输入 | 用途 |
|---|---|
| `date` | 固定窗口结束日补采/复现（留空取最近已到达的十点） |
| `stage` | all/snapshot/funding，日常使用 all |
| `promote=false` | 生成候选产物，保留正式数据；仍可能调用付费接口 |
| `dry_run=true` | 仅输出计划，不调用接口、不更新数据 |
| `skip_search=true` | 跳过可选 Tavily 搜索 |

推荐先运行 `doctor` 和 `run --dry-run`，配置密钥后再执行 `run --no-promote`，检查候选结果后 `run --resume` 发布。CI 不保留候选正文；此恢复流程适用于本地。

本地分阶段调试（需 `.env` 配置 `MANUS_API_KEY` / `DEEPSEEK_API_KEY`，参考 `config/env.example`；
也可用设置页免手改：`node scripts/settings-server.mjs` 后打开 Next.js 应用「设置」视图保存）：

以下旧 CLI 示例仍按自然日运行。新的固定十点窗口需给 discovery/content/feed 三个 CLI 都加 `--ten-am`，date 改为窗口结束日；日常推荐统一入口，避免混用路径。

```powershell
python scripts/manus_source/runner.py --date 2026-08-16 --groups group_a   # 阶段 A 发现
python scripts/manus_source/content_phase.py --date 2026-08-16             # 阶段 B 正文（脚本爬虫）
python scripts/build_manus_feed.py --date 2026-08-16 --no-promote          # 阶段 C 校验
python scripts/build_manus_feed.py --date 2026-08-16                       # 原子晋升
```

新增账号或逐一校准现有账号时，先运行不联网的配置审计，再使用单账号 canary：

```powershell
python scripts/audit_manus_sources.py
python scripts/audit_manus_sources.py --check-links
python scripts/manus_source/runner.py --date 2026-09-10 --ten-am --account "机器之心" --allow-paid
```

单账号 canary 默认在观察到 20 credits 时停止。仅在默认阈值已经安全收口、且需要判断任务是否接近完成时，可显式设置 `--canary-credit-limit 10..60`；每次仍只创建一个 Lite 任务、无创建重试，并在报告中记录阈值。

`--check-links` 对每个主页发送一次小体积 GET，不重试、不读取或保存正文，也不调用 Manus/模型。账号级状态保存到已忽略的 `work/source-audit/source-health-<date>.json`，用于发现主页失效、跳转和访问限制；它不能代替文章日期、身份和发现质量校验。

单账号 canary 只提交一个 Manus Lite 发现任务，创建不重试，最长等待 600 秒；轮询观察到 20 credits 或异常时请求停止。同一账号同一天只能尝试一次，调用前后余额和结果写入 `work/manus/ten-am/canary/<账号哈希>/<date>/canary-report.json`。发现 JSON 保存在同目录的 `raw/`，通过同账号、同窗口契约验证的成功结果可由逐来源生产入口复用；仍须合并并验证完整三组审计，不能直接复制绕过组契约。20 credits 是观察停止线，不是服务端硬性账单上限。

上例 group_a 仅用于发现阶段冒烟；进入正文和 feed 前必须补齐同日三组发现结果。原 CLI 独立执行，不具备统一入口的整套产物保护。

> 阶段 B 默认本地脚本爬虫（`MANUS_CONTENT_MODE=script`，需 `pip install trafilatura`）：
> urllib 抓取文章页 → trafilatura 提取正文 → 跳转漂移/风控/过短判定 → 产出与 Manus 相同契约。
> 回退：`MANUS_CONTENT_MODE=manus` 走原 Manus 正文任务路径（见 `docs/history/2026-08-20-manus-pipeline-smoke-issues.md`）。

## 3. 断点续跑与重试

- 逐来源缓存与成功 canary 记录 `sourceIdentity`（账号、平台、主页）。换入口或旧零条缓存缺少入口证据时，默认返回 `source_config_unverified`，保留费用锁；明确核对预算后才使用失败重试。旧缓存中的文章三元组全部匹配当前入口时仍可复用。修改模板不会自行重试同窗口失败来源。
- 十点窗口使用 `manus_discovery_window.md`：同 URL 的已核实别名、每次最多 30 秒列表等待、图文选择一次、原 URL 重开一次；失败区分身份、列表、详情时间、扫描边界。阶段进度只供排障，未通过最终 JSON/窗口契约的文章不入库。

- 同一日期重跑正文时仅复用契约通过的成功 URL，失败和缺失 URL 重新抓取。
- 统一入口按来源复用同窗口尝试；失败来源默认不重新付费。旧按组 CLI 的 `--resume` 仍仅复用全来源成功的组。
- feed 契约或可发布性校验失败时保留上一次 `current.json`。统一入口失败状态在 `work/runs/`，原 feed CLI 状态在指定 data-dir。

## 4. 成本控制

- 统一入口逐来源创建发现任务，最多 20 个、并发 3 个；同窗口缓存命中的来源不创建任务；正文阶段默认本地脚本爬取，**不再产生 Manus 正文任务**。
  回退 `MANUS_CONTENT_MODE=manus` 时任务数取决于批次大小与失败重试。当前配置为 20 个账号。
- 控制成本：只运行必要阶段，复用成功缓存，单组 discovery 冒烟。`promote=false` 仅控制发布，不能免除接口费用。
- 账号来源校准优先使用单账号 canary。首次接入逐个验证账号身份、主页、文章时间和原文链接；日常按失败率轮换复测，不每天重复创建 20 个测试任务。
- 正文加工模型预算独立于打标签：`config/taxonomy.json → enrich` 块（并发/预算/超时），
  长正文调用不得沿用 `model.budget_seconds`。
- 缓存：`data/manus/enrichment_cache.json`，键含正文哈希 + taxonomy/prompt/模型版本；
  成功缓存可复用，fallback/失败缓存重新尝试；失败重试仍可能产生费用。
- 爬虫礼貌性：`MANUS_CRAWL_REQUEST_DELAY_SECONDS`（默认 1s）+ `MANUS_CRAWL_CONCURRENCY`（默认 4），
  降低被目标平台风控的概率。

## 5. 故障恢复

| 症状 | 诊断入口 | 处置 |
|---|---|---|
| 工作流失败 | Actions 日志 + pipeline-status Artifact | 按错误类型重跑；429/限额 → 降并发或延后 |
| 页面显示“公众号源不可用/过期” | `data/manus/state.json` | 手动补采目标日期并晋升 |
| 某账号持续 failed | 本地发现结果的 `source_audits` | 主页 URL 失效/平台改版 → 更新 `config/manus_sources.json` |
| 正文大量风控失败 | 诊断 summary 的 failed 列表 | 属目标站点风控（CI 数据中心 IP 更易触发），等待恢复或临时 `MANUS_CRAWL_JINA_FALLBACK=true`；不伪造正文 |
| 正文批量“无法从页面提取正文” | 诊断 summary 的 failed 列表 | 平台改版导致 trafilatura 失效：本地抓一页 URL 调试提取，必要时临时 `MANUS_CONTENT_MODE=manus` 回退 |
| 正文批量“抓取失败” | 诊断 summary 的 failed 列表 | 网络/超时：检查 `MANUS_CRAWL_TIMEOUT_SECONDS/RETRIES`，或 CI runner 网络策略 |
| feed schema 疑似有问题 | `python -m unittest tests.pipeline.test_manus_contract -v` | 消费者回退：临时让快照读取 `data/manus/archive/<上一成功日>.json` |

## 6. 回滚

- Manus 持续失败：保留最近成功 `current.json`，快照照常运行（页面显示过期），**不恢复 WeRead**。
- 快照集成异常：回退 `build_snapshot.py` 与模板到切换前提交，保留 Manus 生产数据。
- 历史归档不回滚、不重写；一切切换只影响新增量。

## 7. 账号清单扩容（渐进策略）

候选池在 `config/accounts.json`（不再被生产链路调用）。流程：
1. 为候选账号找到稳定的公开主页 URL（腾讯新闻/网易号/白鲸等已支持平台）。
2. 在本地候选配置中加入账号，用 discovery CLI 的 `--groups <所在组>` 冒烟 2-3 天，确认 `source_audits` 稳定 complete。
3. 通过后正式写入 `config/manus_sources.json`（唯一配置源），同步更新发现 prompt 的平台规则
   （若引入新平台）。

## 8. 安全红线

- `MANUS_API_KEY` / `DEEPSEEK_API_KEY` 只存 GitHub Secrets 或本地 `.env`（已 gitignore；
  可用设置页 `scripts/settings-server.mjs` 写入，页面响应不回显明文）。
- 正文全文只存在于运行时 `work/`（已 gitignore）；当前 Artifact 只上传统一编排的 `state.json`，不上传原始结果或正文。
- 分发打包（见外层 `DISTRIBUTE.md`）不得携带 key、正文与本地 `.env`。
