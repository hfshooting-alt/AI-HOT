# Manus 信源运维手册（MANUS_SOURCE_RUNBOOK）

> 适用：`.github/workflows/fetch-manus.yml` + `scripts/manus_source/` + `scripts/build_manus_feed.py`
> 架构背景见 `docs/history/2026-08-17-manus-only-source-migration-plan.md` 与外层 `docs/PIPELINE.md`

## 1. 日常运行（全自动）

- 定时：每天北京时间 01:00（UTC 17:00），目标日期 = 北京时间昨天，08:00 快照前完成晋升。
- 快照工作流（08:00/13:00/20:00）**不调用、不等待 Manus**，只读 `data/manus/current.json`。
- 失败自动创建/复用告警 Issue「⚠️ Manus 信源采集告警」；恢复成功后自动评论并关闭。

## 2. 手动运行与调试

Actions 页 → `Manus 公众号采集并晋升 feed` → Run workflow：

| 输入 | 用途 |
|---|---|
| `date` | 固定历史日期补采/复现（留空 = 昨天） |
| `groups` | 低成本冒烟：只填 `group_a` |
| `promote=false` | 只校验不晋升 `current.json`（零生产影响） |

推荐冒烟序列：`group_a + promote=false` → 全组 + `promote=false` → 全组 + `promote=true`。

本地分阶段调试（需 `.env` 配置 `MANUS_API_KEY` / `DEEPSEEK_API_KEY`，参考 `.env.example`；
也可用设置页免手改：`node scripts/settings-server.mjs` 后打开 Next.js 应用「设置」视图保存）：

```powershell
python scripts/manus_source/runner.py --date 2026-08-16 --groups group_a   # 阶段 A 发现
python scripts/manus_source/content_phase.py --date 2026-08-16             # 阶段 B 正文（脚本爬虫）
python scripts/build_manus_feed.py --date 2026-08-16 --no-promote          # 阶段 C 校验
python scripts/build_manus_feed.py --date 2026-08-16                       # 原子晋升
```

> 阶段 B 默认本地脚本爬虫（`MANUS_CONTENT_MODE=script`，需 `pip install trafilatura`）：
> urllib 抓取文章页 → trafilatura 提取正文 → 跳转漂移/风控/过短判定 → 产出与 Manus 相同契约。
> 回退：`MANUS_CONTENT_MODE=manus` 走原 Manus 正文任务路径（见 `docs/history/2026-08-20-manus-pipeline-smoke-issues.md`）。

## 3. 断点续跑与重试

- 同一日期重跑时，已存在的合法正文批次自动复用（`ContentPipeline` 续跑），只重跑缺失批次。
- 发现阶段无续跑：整组重新提交（发现结果文件是原子的，三组缺一不可晋升）。
- 组整体失败或 schema 不合法：**不覆盖**上一次 `current.json`，只在 `state.json` 记录失败。

## 4. 成本控制

- 每天 Manus 任务数 = 3（发现）固定；正文阶段默认本地脚本爬取，**不再产生 Manus 正文任务**。
  回退 `MANUS_CONTENT_MODE=manus` 时 ≈ ceil(文章数/4) 个正文任务（14 账号日均 10-20 篇时约 6-8 个任务）。
- 降低成本：`MANUS_AGENT_PROFILE=manus-1.6-lite`、缩小 `groups` 冒烟、`promote=false` 演练。
- 正文加工模型预算独立于打标签：`config/taxonomy.json → enrich` 块（并发/预算/超时），
  长正文调用不得沿用 `model.budget_seconds`。
- 缓存：`data/manus/enrichment_cache.json`，键含正文哈希 + taxonomy/prompt/模型版本；
  重复运行不重复付费。
- 爬虫礼貌性：`MANUS_CRAWL_REQUEST_DELAY_SECONDS`（默认 1s）+ `MANUS_CRAWL_CONCURRENCY`（默认 4），
  降低被目标平台风控的概率。

## 5. 故障恢复

| 症状 | 诊断入口 | 处置 |
|---|---|---|
| 工作流红 + 告警 Issue | Action 日志 + `state.json.failure` | 按错误类型重跑；429/限额 → 降并发或延后 |
| 页面显示“公众号源不可用/过期” | `data/manus/state.json` | 手动补采目标日期并晋升 |
| 某账号持续 failed | 诊断 Artifact 的 `source_audits` | 主页 URL 失效/平台改版 → 更新 `config/manus_sources.json` |
| 正文大量风控失败 | 诊断 summary 的 failed 列表 | 属目标站点风控（CI 数据中心 IP 更易触发），等待恢复或临时 `MANUS_CRAWL_JINA_FALLBACK=true`；不伪造正文 |
| 正文批量“无法从页面提取正文” | 诊断 summary 的 failed 列表 | 平台改版导致 trafilatura 失效：本地抓一页 URL 调试提取，必要时临时 `MANUS_CONTENT_MODE=manus` 回退 |
| 正文批量“抓取失败” | 诊断 summary 的 failed 列表 | 网络/超时：检查 `MANUS_CRAWL_TIMEOUT_SECONDS/RETRIES`，或 CI runner 网络策略 |
| feed schema 疑似有问题 | `python -m unittest tests.test_manus_contract -v` | 消费者回退：临时让快照读取 `data/manus/archive/<上一成功日>.json` |

## 6. 回滚

- Manus 持续失败：保留最近成功 `current.json`，快照照常运行（页面显示过期），**不恢复 WeRead**。
- 快照集成异常：回退 `build_snapshot.py` 与模板到切换前提交，保留 Manus 生产数据。
- 历史归档不回滚、不重写；一切切换只影响新增量。

## 7. 账号清单扩容（渐进策略）

候选池在 `config/accounts.json`（不再被生产链路调用）。流程：
1. 为候选账号找到稳定的公开主页 URL（腾讯新闻/网易号/白鲸等已支持平台）。
2. 用 `groups=<新号所在组> + promote=false` 冒烟 2-3 天，确认 `source_audits` 稳定 complete。
3. 通过后正式写入 `config/manus_sources.json`（唯一配置源），同步更新发现 prompt 的平台规则
   （若引入新平台）。

## 8. 安全红线

- `MANUS_API_KEY` / `DEEPSEEK_API_KEY` 只存 GitHub Secrets 或本地 `.env`（已 gitignore；
  可用设置页 `scripts/settings-server.mjs` 写入，页面响应不回显明文）。
- 正文全文只存在于运行时 `work/`（已 gitignore）；Artifact 只上传去正文诊断目录，
  上传前有防泄漏断言（content_text / 密钥字段检测）。
- 分发打包（见外层 `DISTRIBUTE.md`）不得携带 key、正文与本地 `.env`。
