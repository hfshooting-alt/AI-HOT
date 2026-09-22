# 前端工程测试

`frontend/` 检查新闻Daily SSR、导航与来源展示；`api/` 检查 Manus 双池边界和已退役的外部新闻代理不会发起请求；`settings/` 检查仓库根设置服务。

从仓库根运行 `npm --prefix web test`，先构建再运行全部 Node 测试。无需构建的快速检查使用 `npm --prefix web run test:unit`。

Python 流水线测试位于仓库根 `tests/pipeline/`。
