# 前端工程测试

`frontend/` 检查 SSR 与来源展示；`api/` 检查分页和接口响应；`settings/` 检查仓库根设置服务。

从仓库根运行 `npm --prefix web test`，先构建再运行全部 23 项 Node 测试。无需构建的快速检查使用 `npm --prefix web run test:unit`。

Python 流水线测试位于仓库根 `tests/pipeline/`。
