# AIHOT 数据源接入

## 当前接入

站点使用 AIHOT 匿名只读 API，不需要 API Key，也不会产生模型调用费用。生产代码仅使用稳定的 `https://aihot.virxact.com/api/v1/*` 路径：

- `GET /api/v1/items`：全部动态；
- `GET /api/v1/hot-topics`：热点榜及信源数量；
- `GET /api/v1/daily`：日报索引和日报正文。

条目同时保留 AIHOT 收录页和原始报道链接。热点排名、信源数均直接采用 API 返回值，站点不自行推算热度。

## 本地候选数据

审核数据放在被 Git 忽略的 `work/aihot-preview/<日期>/` 中。先按 API 文档抓取响应，再生成仅供本地预览的快照：

```powershell
node scripts/build_aihot_preview.mjs `
  --input work/aihot-preview/2026-09-09 `
  --baseline web/public/snapshot.json `
  --output work/aihot-preview/site/snapshot.json
```

脚本强制输出到 `work/`，避免未经审核的数据被误提交。候选快照包括过去 24 小时全部动态、热点榜和最新日报；站点不再建立单独的精选数据集。

每日十点流水线会向 `build_snapshot.py` 传入 `--api-window 24h`，正常约 5 页即可覆盖当前数据量。只有人工重建历史时才使用 7 天窗口，避免日常运行做无用分页。

没有 Manus 或模型密钥时，可直接运行统一的候选模式：

```powershell
python scripts/run_pipeline.py run --source-mode aihot-only --no-promote
```

该模式只执行 snapshot，自动跳过模型打标，并保留 24 小时窗口内的全部条目。GitHub Actions 手动运行也提供同名 `source_mode` 选项。

## 当前用途与处理方式

AIHOT 的公开规则明确允许个人非商业、公益非商业和公司/组织内部使用匿名免费接入。本项目定位为内部 AI 情报工具，AIHOT 是上游数据源之一，可以直接用于该用途。

本站定位为多源内部 AI 情报加工系统。进入展示前，数据会经过固定十点窗口过滤、ID/标题/URL 去重、Manus 公众号补充、分类与标签、栏目编排、日报/周报归档、公司与产品实体抽取及融资信息整理；页面保留 AIHOT 收录页、原始报道链接和来源标识，便于溯源。

当前 `github.io` 地址在技术上可被互联网访问，这与产品的内部使用目的属于两个不同维度。如果后续承载敏感内部信息，应另行使用带访问控制的托管。若用途改变为收费产品、客户交付、代理接口、数据转售、AIHOT 公开副本或对外批量再分发，再按 AIHOT 规则申请书面授权。
