# 自动数据流水线

统一入口为 `scripts/run_pipeline.py`，命令从仓库根目录执行。原有分阶段 CLI 继续可用。日常操作优先使用统一入口，获取运行前检查、候选产物隔离、阶段记录与发布恢复。

## 1. 先检查，再运行

后续测试统一遵循[测试成本控制](TESTING_COST_CONTROL.md)。默认先 `python scripts/test_pipeline.py`；确认 Manus 密钥用 `python scripts/test_pipeline.py manus-auth`。本页 `run` 生产命令会执行真实接口，`--no-promote` 不限制费用。

```sh
python -m pip install -r scripts/requirements.txt
python scripts/run_pipeline.py doctor
python scripts/run_pipeline.py run --dry-run --date 2026-09-07
```

`doctor` 检查配置、依赖、模板、必要密钥是否存在和输出目录是否可写；只创建随后关闭删除的临时探针，不调用外部接口，不输出密钥。它不能验证余额、密钥有效性和网络可用性。缺项返回非零退出码。

`--dry-run` 仅打印阶段及命令，不写数据、不调用接口，也不要求配置密钥。

按 `config/env.example` 在根目录 `.env` 配置 Manus 与模型密钥。Tavily 搜索为可选。完成配置后：

```sh
# 实际采集和加工，生成候选产物；会调用外部接口并可能产生费用
python scripts/run_pipeline.py run --date 2026-09-07 --no-promote

# 检查候选产物后，复用成功阶段并发布
python scripts/run_pipeline.py run --date 2026-09-07 --resume

# 直接完成整套更新
python scripts/run_pipeline.py run
```

默认 `--window-mode ten-am`，`--date` 是窗口结束日。例如 `--date 2026-09-09` 固定覆盖 9 月 8 日 10:00（含）至 9 月 9 日 10:00（不含）。省略日期时取最近已经到达的北京时间十点：十点前取前一天，十点及以后取当天。子阶段复用这个已确定的日期，排队延迟和加工耗时不移动窗口。跨日补跑需显式填写窗口结束日。

兼容旧数据时用 `--window-mode calendar-day --date YYYY-MM-DD`，含义仍为该自然日。原有 discovery/content/feed CLI 默认保留自然日模式，加 `--ten-am` 启用新窗口。旧三组文件与十点文件分开存储，不能混用。

十点模式要求发现结果带详情页明确的 `published_at`，缺少具体时间的边界日来源会被标记失败，不能把中午 12 点等虚构时间当作采集证据。快照的上游新闻也按同一窗口过滤新增入库，日报显示明确起止时刻；周报、历史页和融资表继续保留各自历史范围，热点榜仍是抓取时的榜单。归档保留与过期规则按实际运行时间执行，历史补跑不回拨网站时钟，也不重写已定稿历史。

## 2. 阶段与输入

| 阶段 | 输出/前置要求 |
| --- | --- |
| `discovery` | Manus 发现三组账号的窗口文章，原始结果在 `work/manus/ten-am/<date>/raw/` |
| `content` | 读取同日三组发现结果，默认脚本提取正文；成功正文可复用 |
| `feed` | 读取发现和正文结果，经模型加工后生成候选 Manus feed |
| `snapshot` | 合并 AIHOT 与候选/既有 Manus feed，生成快照、归档、历史页及周报 |
| `funding` | 从候选/既有快照和 feed 抽取融资表，可选搜索补全 |

默认 `--stage all` 按上述顺序运行。`--stage <阶段>` 只运行指定阶段，不自动补齐其前置阶段。单独运行 content/feed 时需要同日期完整三组发现文件；funding 至少需要一份有效快照或 feed。

`--skip-search` 跳过可选 Tavily 搜索。单组试采仍用原 CLI `python scripts/manus_source/runner.py --date YYYY-MM-DD --groups group_a`，下游生产契约继续要求三组结果。

## 3. 失败保护与断点恢复

每次新运行把既有产物复制到 `work/runs/<date>/ten-am/<run-id>/workspace/`（旧自然日模式没有 ten-am 层）。所有选定阶段成功后，再校验候选输出并替换对应正式目录：

- feed：`data/manus/`。
- snapshot：`data/archive/`、`data/cache/`、`web/public/`。
- funding：`data/funding/`、`web/public/`。

阶段失败时停止后续步骤，正式产物保持原样，候选数据和缓存保留。`--no-promote` 运行各阶段自身校验并保留候选；最终跨产物一致性检查在发布时执行。

融资输入存在且全部抽取失败（含未完成任务）时拒绝覆盖旧表。发现过文章或账号失败、最终却没有可发布文章时，拒绝覆盖旧 feed。来源均成功且确实无新闻，或者融资抽取成功且没有公司，允许生成空结果。部分失败仍沿用现有 degraded/统计语义。

```sh
python scripts/run_pipeline.py run --date 2026-09-07 --resume
```

恢复最近同日期运行时，保持原阶段和 `--skip-search` 选择。已成功阶段直接复用，失败阶段重新执行。发现阶段仅复用契约有效且全部来源成功的组；正文仅复用成功 URL；加工缓存仅复用 `complete`，旧 fallback 会重新尝试。同 URL 的后续成功正文优先于历史失败记录。

代码、业务配置或模型名/接口地址/正文模式发生变化会拒绝恢复，要求新建运行。密钥值不进入签名，可补齐或更换。若正式产物已被其他运行更新，旧候选不得覆盖较新的数据。

发布使用目录备份和日志：异常时回滚；进程被强制终止后，下次同次运行的 `--resume` 恢复未完成发布。多个目录的替换不是面向并发读者的全局原子事务；Git 提交后的整套文件才是同一发布版本。

`work/pipeline.lock` 防止统一入口并发写入。强制终止可能留下锁；先确认没有运行中的流水线，再处理残留锁并恢复原运行。单阶段原 CLI 不受此锁管理，勿与统一入口同时写入正式产物。

## 4. 日志与溯源

`work/runs/<date>/ten-am/latest.json` 指向最近十点运行，旧自然日模式使用 `work/runs/<date>/latest.json`。每次运行的 `state.json` 保存固定 collectionWindow、阶段、状态、退出码、耗时和发布状态；`publication.json` 记录目录替换状态；`backup/` 保留发布前版本。运行目录和原始正文在 Git 忽略范围内，不会自动清理，磁盘维护时确认运行完成后按日期归档或移除。

正式数据失败时保留旧版本，因此应结合运行状态判断更新是否完成，不能只看页面能否打开。运行状态不含密钥或正文；排错时避免分享 `.env` 或原始全文。

## 5. GitHub Actions

`.github/workflows/fetch-manus.yml` 每天北京时间 10:00（UTC 02:00）开始全流程，测试通过后调用统一入口，成功后将整套正式数据提交到仓库；并非十点整完成更新。GitHub schedule 可能延迟，不能保证准点。手动输入为 `date`（窗口结束日）、`stage`、`promote`、`dry_run`、`skip_search`；可选阶段为 all/snapshot/funding。独立 content/feed 所需原始正文未存入 Git，所以这两个阶段仅在保留原始文件的本地运行。

需要 GitHub Secrets `MANUS_API_KEY`、`DEEPSEEK_API_KEY`；可选 `TAVILY_API_KEY`，模型接口和模型名可用 Variables `LLM_API_BASE`、`LLM_MODEL`。如果修改 taxonomy 中 `api_key_env`，同步工作流的密钥注入。

工作流只上传 `state.json`，保留 7 天。原始结果、正文、候选产物和密钥不上传。CI 作业之间暂不支持断点续跑；本地保留 work 目录时可以恢复。失败查看 Actions 日志与状态 Artifact。

这条任务更新仓库数据；Next.js 的线上构建和托管发布需要另行接通。离线样本测试证明编排和保护机制，真实密钥、额度、全账号抓取和托管部署仍需实际验证。
