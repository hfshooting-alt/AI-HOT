# 轻量清理与 exporter 核验

2026-09-10 查阅上游 README 与维护者公告：wechat-article-exporter 于2026-07-30停止维护，核心微信同步接口关闭，剩余 Credential 通道未接入主流程，不能作为本项目最新24小时采集的可靠替代方案。本轮未安装、未登录、未调用付费服务。此结论限该项目，不证明WeRSS全部模式不可用，也不解释先前本地HTTP登录失败的具体根因。

- https://github.com/wechat-article/wechat-article-exporter
- https://github.com/wechat-article/wechat-article-exporter/issues/200

## 仓库整理

以下文件从 docs/operations/ 移至本目录，保留原名与内容，入口链接同步：

- SOURCE_DIAGNOSIS_20260910.md
- 2026-09-10-PIPELINE_REVIEW.md

operations/ 保留持续有效的运行手册，history/ 保存日期型实测记录。没有修改生产代码、采集配置或业务数据。

## 本地工作区整理

旧重构的临时脚本、payload和日志从外层tmp/归入archive/2026-09-10/old-refactor/；根截图归入screenshots/；两份失败HTTP登录探针在local-services/werss/archive/2026-09-10/以.py.txt保留，作为历史源码不再作为启动入口。

32次文件移动逐一校验SHA256，精确旧路径、新路径与哈希存于外层archive/2026-09-10/moves.json（本地，不提交）。没有删除密钥、微信会话、正文、付费缓存、候选预览、依赖环境或旧Git检出目录。当前服务入口不变。
