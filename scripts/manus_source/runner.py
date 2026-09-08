"""runner.py — Manus 信源采集运行器（阶段 A：URL 发现；阶段 B 正文提取见 pipeline.py）。

用法:
    python scripts/manus_source/runner.py --date 2026-08-16 --groups group_a group_b group_c
    python scripts/manus_source/runner.py                 # 默认昨天（北京时间）、全部组

行为：按组并发提交 Manus 发现任务 → 轮询 structured output → contracts 严格校验
→ 原始结果写 work/manus/<date>/raw/discovery-<group>.json。任一组失败 exit 1。
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manus_source import contracts  # noqa: E402
from manus_source.client import ManusClient  # noqa: E402
from manus_source.config import Settings, load_sources, render_sources_block  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("group_a", "group_b", "group_c")
DISCOVERY_BRIEF = ("仅处理该 source_group；仅采集 published_date 等于 target_date 的文章。"
                   "发现阶段只输出元数据与 URL，不提取正文。")


def default_target_date() -> str:
    return (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)).isoformat()


def render_discovery_prompt(template_path: Path, sources: list[dict]) -> str:
    template = template_path.read_text(encoding="utf-8")
    if "{{SOURCES}}" not in template:
        raise RuntimeError("发现 prompt 缺少 {{SOURCES}} 占位符")
    return template.replace("{{SOURCES}}", render_sources_block(sources))


def run_discovery(client: ManusClient, group: str, target_date: str, prompt_text: str,
                  expected_accounts: list[str]) -> dict:
    """提交单组发现任务并等待结果；契约校验通过后返回原始 payload，失败抛异常。"""
    task = client.create_crawl_task(
        prompt_text=prompt_text,
        source_group=group,
        target_date=target_date,
        title=f"AI 新闻采集 {target_date} · {group}",
        task_brief=DISCOVERY_BRIEF,
    )
    print(f"[{group}] Manus task created: {task.task_url}", flush=True)
    payload = client.wait_for_structured_result(task.task_id)
    # schema_version 是本地契约版本号，Manus 平台只是通用执行器、不理解其语义
    # （见 docs/2026-08-20-manus-pipeline-smoke-issues.md 问题 1）：不依赖 Manus
    # 回显，落盘校验前本地权威补充；校验端保持强制不变。
    payload["schema_version"] = contracts.DISCOVERY_SCHEMA_VERSION
    contracts.validate_discovery(payload, group, target_date, expected_accounts)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manus 公众号采集运行器")
    parser.add_argument("--date", default=default_target_date(), help="目标日期 YYYY-MM-DD（北京时间）")
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=list(GROUPS))
    parser.add_argument("--resume", action="store_true", help="复用同日校验通过且来源全部成功的发现组")
    args = parser.parse_args(argv)

    settings = Settings.from_environment(PROJECT_ROOT)
    groups_cfg = load_sources(settings.sources_path)
    client = ManusClient(
        api_key=settings.manus_api_key,
        agent_profile=settings.manus_agent_profile,
        poll_seconds=settings.poll_seconds,
        timeout_seconds=settings.timeout_seconds,
        register_grace_seconds=settings.register_grace_seconds,
    )

    raw_dir = settings.work_dir / args.date / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=max(1, len(args.groups))) as ex:
        futs = {}
        for group in args.groups:
            sources = groups_cfg[group]
            prompt_text = render_discovery_prompt(settings.discovery_prompt_path, sources)
            accounts = [s["account_name"] for s in sources]
            if args.resume:
                try:
                    cached = json.loads((raw_dir / f"discovery-{group}.json").read_text(encoding="utf-8"))
                    contracts.validate_discovery(cached, group, args.date, accounts)
                    if all(a["source_status"] == "complete" for a in cached["source_audits"]):
                        results[group] = cached
                        print(f"[{group}] 复用已校验的发现结果", flush=True)
                        continue
                except (OSError, ValueError, contracts.ContractError):
                    pass
            futs[ex.submit(run_discovery, client, group, args.date, prompt_text, accounts)] = group
        for fut in as_completed(futs):
            group = futs[fut]
            try:
                payload = fut.result()
                results[group] = payload
                out = raw_dir / f"discovery-{group}.json"
                out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                complete = sum(1 for a in payload["articles"] if a["extraction_status"] == "complete")
                failed_sources = sum(1 for a in payload["source_audits"] if a["source_status"] == "failed")
                print(f"[{group}] 发现完成：{complete} 篇文章，{failed_sources} 个来源失败，已保存 {out}",
                      flush=True)
            except Exception as error:  # noqa: BLE001 - 组级失败隔离，不拖垮其他组
                failures.append(f"{group}: {error}")
                print(f"[{group}] 发现失败：{error}", flush=True)

    if failures:
        print("Manus 发现阶段存在失败组：\n" + "\n".join(failures), file=sys.stderr)
        return 1
    print(f"全部 {len(results)} 组发现完成并通过契约校验（{args.date}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
