# 失败后的加密保存与恢复

每日采集仍按北京时间09:30触发。恢复功能不新增定时任务、不重跑采集、不自动调用模型。

## 保存内容

调度记录`work/schedule-audit.json`与发布记录`work/publication-receipt.json`同时保留在状态Artifact和加密包。后者绑定实际推送的数据SHA、公开文件摘要及Pages触发请求状态；`accepted`不代表部署完成。缺少回执时不得推定发布成功，须从日志、提交及独立Pages运行补证。来源级任务执行证据保存在原Manus目录内的费用报告`sourceReceipts`，随原目录一起加密保存。

正常工作流无论成功或失败，结束时将工作区阶段状态、AIHOT输入、Manus原始结果/正文、成功模型缓存、公司资料发现记录、候选快照及公开静态资源加密上传为 `pipeline-recovery-<运行ID>`，保留7天。正文、候选和模型响应不作为明文Artifact或网页发布。仅选取指定工作目录与文件类型，不打包.env、脚本、依赖目录；加密前检查已知API密钥不能混入文件。

正文加工、公司抽取和融资抽取逐批/逐条写成功缓存，缓存采用临时文件加原子替换，降低中断丢失。失败输出不伪装成功缓存。若已经完成本地晋升、之后git push失败，恢复包也收集移入正式目录的本轮结果。

模型错误按安全类别及 HTTP 状态记录到 `work/llm-failures.jsonl`，该文件随加密恢复包保存，不包含密钥、请求正文或服务端错误原文。相关性、摘要、公司和融资阶段在认证、权限、余额、限流或配置错误时停止新请求；其他模型故障连续三次时停止。已在途请求收口并保留成功缓存。旧缓存不能掩盖本轮新请求全部失败；内容证据不合格仍按文章隔离，不算服务故障。旧候选缺失模型成功统计且有融资失败时，需要重建，不能直接批准发布。 公司与融资结构化输出容量分别默认 6144、3072 tokens，可通过各阶段 max_output_tokens 覆盖；不更改提示词版本或成功缓存键。历史 work/ 一次性脚本不属于生产入口，复用前须核对参数包装器，避免重复传递 max_tokens。

Manus 诊断区分 `stopAccepted`（服务接受停止请求）和 `stopSucceeded`（确认远端终态），`remoteStatus` 保留允许的状态值。未确认停止时不再创建排队中的新任务；正常确认停止仍执行并发最多三条、所有来源依次尝试。确认停止和回收文章是两个独立检查，停止本身不代表已找到文章或覆盖完整窗口。

加密采用cryptography的Fernet认证加密；通过HKDF和独立用途标识，从现有Secret派生加密密钥，包内携带随机盐。优先使用可选`PIPELINE_RECOVERY_KEY`，否则依次使用`PARATERA_API_KEY`、`DEEPSEEK_API_KEY`、`MANUS_API_KEY`。不需要新增Secret即可开始保存。恢复必须使用保存时同一密钥；轮换API密钥前保留旧密钥，或先解密归档。丢失旧密钥不能恢复旧包。官方原语说明：[Fernet](https://cryptography.io/en/latest/fernet/)。

Artifact只有在上传完成后才持久保存；runner被强制销毁、任务整体硬超时或上传失败仍可能丢失未上传结果。单个包明文上限512MiB，超限明确失败。此版本只在作业收尾上传，不声称能抵抗任意时刻runner断电。

## GitHub恢复入口

零模型调用的演练入口为 **加密恢复云端演练（固定数据零模型调用）**。两个独立runner分别生成固定失败样本并加密上传、下载解密并执行真实缓存重建及发布前校验。它只使用`work/recovery-rehearsal`中的隔离目录；验证2条模拟新闻、1家模拟公司、1个产品和1条融资记录，并检查缓存缺失/包损坏被拒绝及正式数据校验值不变。权限仅contents:read，没有数据提交或Pages部署步骤。Artifact名称带`synthetic`，不得用于正式批次恢复。

Actions → **从加密缓存恢复数据（不调用模型）** → Run workflow：

1. `run_id` 填原采集运行ID，必须已有 `pipeline-recovery-<ID>`。
2. `promote=false` 默认只生成、校验恢复候选。
3. 缓存与校验通过后，可用 `promote=true` 执行相同恢复并发布，随后自动部署Pages。

恢复流程仅有下载Artifact和git/Pages操作访问GitHub；重建命令禁止网络与子进程，未给模型注入API密钥。模型缓存缺项、提示词版本变化导致缓存失配时，先列出文章ID并停止，不创建任何新任务或补发请求。报告在 `recovery-report-<恢复运行ID>` 中。

当前支持**新闻和快照已成功，后续公司/融资组装或发布失败**的无模型恢复。公司与融资提取所需成功缓存必须齐全；例如融资阶段尚未开始且需要新的模型结果，会列出融资缺项，不能无费用完成发布。公司可选联网补全仅回放独立账本中的成功建议，不搜索、不读网页、不请求模型、不新占费用额度，并保留原资料日期。缺少成功建议的字段继续留空。新闻/快照尚未完成的包仍可解密查看和复用已有结果，但不自动重跑其付费阶段。

work/company-research-budget 中的账本、成功建议、版本缓存和请求占位一起加密保存；旧版 company-web-research 的请求占位也保留。仅接受指定研究目录内 64 位十六进制文件名的 .attempt，不扩大通用文件白名单。恢复在独立目录进行，不覆盖当前运行的云端租约。云端固定数据演练同时验证“补全成功但尚未发布”的字段恢复，以及原 checkedAt/profileUpdatedAt 不被刷新。

原state与fingerprint保持原样；用当前修复代码建立独立恢复候选和来源记录。发布继续通过现有候选审阅、文章集合/窗口/公司范围一致性校验、当前数据基线与旧批次防覆盖检查。恢复记录不能表示原失败运行已经成功。

还会用跨系统一致的文件校验值对照原运行基线。原运行后如已有人工补录或其他数据更新，自动恢复会停止，避免用旧候选覆盖新增内容；需要先合并与复核。Pages触发成功仅记`pagesDeploymentRequested`，实际网页部署结果仍以独立Pages工作流为准。

## 本地恢复

从仓库根目录执行；先安装`scripts/requirements.txt`，设置与保存时相同的`PIPELINE_RECOVERY_KEY`，也可由本地.env提供上述备用密钥。密钥不写进命令行参数。

```powershell
$env:PYTHONPATH = 'scripts'
.venv/Scripts/python.exe -m automation.recovery unpack --path work/download/recovery.bin
# 上一步返回独立解密目录；选择其中 work/runs/<日期>/ten-am/<run-id>
.venv/Scripts/python.exe -m automation.recovery rebuild --path <原运行目录>
# 上一步只有完整通过才返回 reviewDirectory；发布仍有基线与一致性校验
.venv/Scripts/python.exe scripts/run_pipeline.py publish-candidate --candidate <reviewDirectory>
```

9月18日运行35314232820发生在本功能上线前，仅上传2009字节状态诊断，没有可追溯恢复的完整模型缓存。本改动不能找回已经销毁的云端数据。本地另存的七篇Manus采集结果仍保留，恢复当日发布若缺模型结果需另行明确加工范围。
