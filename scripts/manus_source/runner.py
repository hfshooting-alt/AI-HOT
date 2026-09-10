"""runner.py — Manus 信源采集运行器（阶段 A：URL 发现；阶段 B 正文提取见 pipeline.py）。

用法:
    python scripts/manus_source/runner.py --date 2026-08-16 --groups group_a group_b group_c
    python scripts/manus_source/runner.py                 # 默认昨天（北京时间）、全部组

行为：按组并发提交 Manus 发现任务 → 轮询 structured output → contracts 严格校验
→ 原始结果写 work/manus/<date>/raw/discovery-<group>.json。任一组失败 exit 1。
"""
import argparse
import hashlib
import json
import sys
from copy import deepcopy
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manus_source import contracts  # noqa: E402
from manus_source.client import ManusClient, DISCOVERY_OUTPUT_SCHEMA  # noqa: E402
from manus_source.window import ten_am_window  # noqa: E402
from manus_source.config import Settings, load_sources, render_sources_block  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("group_a", "group_b", "group_c")
CANARY_STOP_AT_CREDITS = 20
DISCOVERY_BRIEF = ("仅处理该 source_group；仅采集 published_date 等于 target_date 的文章。"
                   "发现阶段只输出元数据与 URL，不提取正文。")


class DiscoveryRunError(RuntimeError):
    def __init__(self, task_id: str, cause: Exception, *, stop_succeeded: bool,
                 stop_error: str | None = None):
        self.task_id = task_id
        self.stop_succeeded = stop_succeeded
        self.stop_error = stop_error
        super().__init__(str(cause))


def default_target_date() -> str:
    return (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)).isoformat()


def render_discovery_prompt(template_path: Path, sources: list[dict]) -> str:
    template = template_path.read_text(encoding="utf-8")
    if "{{SOURCES}}" not in template:
        raise RuntimeError("发现 prompt 缺少 {{SOURCES}} 占位符")
    return template.replace("{{SOURCES}}", render_sources_block(sources))


def run_discovery(client: ManusClient, group: str, target_date: str, prompt_text: str,
                  expected_accounts: list[str], window: dict | None = None,
                  observed_credit_limit: int | None = None) -> dict:
    """提交单组发现任务并等待结果；契约校验通过后返回原始 payload，失败抛异常。"""
    schema = deepcopy(DISCOVERY_OUTPUT_SCHEMA)
    if window:
        article_schema = schema["properties"]["articles"]["items"]
        article_schema["properties"]["published_at"] = {"type": ["string", "null"]}
        article_schema["required"].append("published_at")
    task = client.create_crawl_task(
        prompt_text=prompt_text,
        source_group=group,
        target_date=target_date,
        title=f"AI 新闻采集 {target_date} · {group}",
        task_brief=(f"只采集 {window['start']}（含）至 {window['end']}（不含）的文章；"
                    "published_at 必须来自详情页明确时间。" if window else DISCOVERY_BRIEF),
        output_schema=schema,
    )
    print(f"[{group}] Manus task created: {task.task_url}", flush=True)
    try:
        payload = client.wait_for_structured_result(
            task.task_id, observed_credit_limit=observed_credit_limit)
    except Exception as error:
        stop_succeeded = False
        stop_error = None
        try:
            client.stop_task(task.task_id)
            stop_succeeded = True
        except Exception as exc:  # noqa: BLE001 - 保留原始异常并显式记录停止失败
            stop_error = str(exc)[:160]
        raise DiscoveryRunError(task.task_id, error, stop_succeeded=stop_succeeded,
                                stop_error=stop_error) from error
    # schema_version 是本地契约版本号，Manus 平台只是通用执行器、不理解其语义
    # （见 docs/2026-08-20-manus-pipeline-smoke-issues.md 问题 1）：不依赖 Manus
    # 回显，落盘校验前本地权威补充；校验端保持强制不变。
    payload["schema_version"] = contracts.DISCOVERY_SCHEMA_VERSION
    if window:
        payload["schema_version"] = contracts.WINDOW_DISCOVERY_SCHEMA_VERSION
        payload["collectionWindow"] = window
    contracts.validate_discovery(payload, group, target_date, expected_accounts)
    return payload


def select_account(groups_cfg: dict, account_name: str) -> tuple[str, dict]:
    """按配置中的精确名称选择唯一账号，避免同名来源静默串组。"""
    matches = [(group, source) for group, sources in groups_cfg.items()
               for source in sources if source["account_name"] == account_name]
    if not matches:
        raise ValueError(f"账号不在 config/manus_sources.json：{account_name}")
    if len(matches) != 1:
        raise ValueError(f"账号名称不唯一，无法执行 canary：{account_name}")
    return matches[0]


def canary_slug(account_name: str) -> str:
    return hashlib.sha256(account_name.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manus 公众号采集运行器")
    parser.add_argument("--date", default=default_target_date(), help="目标日期 YYYY-MM-DD（北京时间）")
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=list(GROUPS))
    parser.add_argument("--resume", action="store_true", help="复用同日校验通过且来源全部成功的发现组")
    parser.add_argument("--ten-am", action="store_true", help="date 为窗口结束日，采集前一日十点至当日十点")
    parser.add_argument("--account", help="单账号低成本 canary；结果隔离且不进入生产 feed")
    parser.add_argument("--allow-paid", action="store_true", help="显式允许单账号 canary 创建一个付费任务")
    parser.add_argument("--canary-timeout-seconds", type=int, default=600,
                        help="单账号 canary 最长等待秒数，范围 60-600（默认 600）")
    args = parser.parse_args(argv)
    if args.account and not args.allow_paid:
        parser.error("--account 需要同时提供 --allow-paid")
    if args.account and args.resume:
        parser.error("单账号 canary 不支持 --resume；同账号同日只允许一次尝试")
    if not 60 <= args.canary_timeout_seconds <= 600:
        parser.error("--canary-timeout-seconds 必须在 60-600 之间")

    settings = Settings.from_environment(PROJECT_ROOT)
    window = ten_am_window(args.date) if args.ten_am else None
    if window:
        settings = replace(settings, work_dir=settings.work_dir / "ten-am",
                           discovery_prompt_path=PROJECT_ROOT / "scripts/prompts/manus_discovery_window.md")
    groups_cfg = load_sources(settings.sources_path)
    canary = None
    if args.account:
        try:
            group, source = select_account(groups_cfg, args.account)
        except ValueError as exc:
            parser.error(str(exc))
        args.groups = [group]
        groups_cfg = {group: [source]}
        settings = replace(
            settings,
            work_dir=settings.work_dir / "canary" / canary_slug(args.account),
            manus_agent_profile="manus-1.6-lite",
            poll_seconds=min(settings.poll_seconds, 5),
            timeout_seconds=min(settings.timeout_seconds, args.canary_timeout_seconds),
        )
        canary = {"accountName": args.account, "sourceGroup": group,
                  "targetDate": args.date, "collectionWindow": window,
                  "agentProfile": "manus-1.6-lite", "createAttempts": 0,
                  "status": "reserved", "resolved": False,
                  "startedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")}
    client = ManusClient(
        api_key=settings.manus_api_key,
        agent_profile=settings.manus_agent_profile,
        poll_seconds=settings.poll_seconds,
        timeout_seconds=settings.timeout_seconds,
        register_grace_seconds=settings.register_grace_seconds,
        create_retries=0 if canary else 3,
    )

    raw_dir = settings.work_dir / args.date / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    canary_path = raw_dir.parent / "canary-report.json"
    if canary:
        if canary_path.exists():
            print(f"该账号当天已有 canary 尝试：{canary_path}", file=sys.stderr)
            return 1
        try:
            canary["balanceBefore"] = client.available_credits()
            if canary["balanceBefore"] < CANARY_STOP_AT_CREDITS:
                raise RuntimeError("Manus 余额低于 canary 保留线")
        except Exception as exc:  # noqa: BLE001 - 余额不可确认时禁止创建任务
            canary.update(status="blocked", error=str(exc)[:160])
            canary_path.write_text(json.dumps(canary, ensure_ascii=False, indent=2), encoding="utf-8")
            print("无法确认 Manus 余额，canary 未创建任务", file=sys.stderr)
            return 1
        canary_path.write_text(json.dumps(canary, ensure_ascii=False, indent=2), encoding="utf-8")
    failures: list[str] = []
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=max(1, len(args.groups))) as ex:
        futs = {}
        for group in args.groups:
            sources = groups_cfg[group]
            prompt_text = render_discovery_prompt(settings.discovery_prompt_path, sources)
            if window:
                prompt_text = prompt_text.replace("{{WINDOW_START}}", window["start"]).replace("{{WINDOW_END}}", window["end"])
            accounts = [s["account_name"] for s in sources]
            if args.resume:
                try:
                    cached = json.loads((raw_dir / f"discovery-{group}.json").read_text(encoding="utf-8"))
                    contracts.validate_discovery(cached, group, args.date, accounts)
                    if cached.get("collectionWindow") == window and all(a["source_status"] == "complete" for a in cached["source_audits"]):
                        results[group] = cached
                        print(f"[{group}] 复用已校验的发现结果", flush=True)
                        continue
                except (OSError, ValueError, contracts.ContractError):
                    pass
            limit = CANARY_STOP_AT_CREDITS if canary else None
            if canary:
                canary["createAttempts"] = 1
                canary_path.write_text(json.dumps(canary, ensure_ascii=False, indent=2), encoding="utf-8")
            futs[ex.submit(run_discovery, client, group, args.date, prompt_text,
                           accounts, window, limit)] = group
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
                if canary and isinstance(error, DiscoveryRunError):
                    canary.update(taskId=error.task_id, stopRequested=True,
                                  resolved=error.stop_succeeded)
                    if error.stop_error:
                        canary["stopError"] = error.stop_error
                print(f"[{group}] 发现失败：{error}", flush=True)

    if canary:
        canary["finishedAt"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        if failures:
            canary.update(status="failed", error=failures[0][:160])
        else:
            payload = results[canary["sourceGroup"]]
            audit = payload["source_audits"][0]
            canary.update(status="complete", resolved=True,
                          sourceStatus=audit["source_status"],
                          articleCount=audit["article_count"])
        try:
            canary["balanceAfter"] = client.available_credits()
            canary["creditsUsed"] = max(0, canary["balanceBefore"] - canary["balanceAfter"])
        except Exception as exc:  # noqa: BLE001 - 结果仍保留，余额差标记不可用
            canary["balanceError"] = str(exc)[:160]
        canary_path.write_text(json.dumps(canary, ensure_ascii=False, indent=2), encoding="utf-8")

    if failures:
        print("Manus 发现阶段存在失败组：\n" + "\n".join(failures), file=sys.stderr)
        return 1
    print(f"全部 {len(results)} 组发现完成并通过契约校验（{args.date}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
