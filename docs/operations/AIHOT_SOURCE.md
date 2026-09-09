# AIHOT 数据源接入

## 当前接入

站点使用 AIHOT 匿名只读 API，不需要 API Key，也不会产生模型调用费用。生产代码仅使用稳定的 `https://aihot.virxact.com/api/v1/*` 路径：

- `GET /api/v1/items`：精选与全部动态；
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

脚本强制输出到 `work/`，避免未经审核的数据被误提交。候选快照包括过去 24 小时精选、全部动态、热点榜和最新日报。

每日十点流水线会向 `build_snapshot.py` 传入 `--api-window 24h`，正常约 5 页即可覆盖当前数据量。只有人工重建历史时才使用 7 天窗口，避免日常运行做无用分页。

## 发布边界

AIHOT 当前条款允许个人非商业、非营利和内部使用。公开镜像、白标产品或批量公开再分发需要事先取得书面授权。取得授权前，候选快照只用于本地 review，不复制到 `web/public/snapshot.json`，也不触发 GitHub Pages 发布。

授权申请应说明站点地址、用途、展示字段、更新频率、是否商业化，以及会保留 AIHOT 收录链接和来源标识。
