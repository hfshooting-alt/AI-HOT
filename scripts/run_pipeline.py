#!/usr/bin/env python3
"""运行入口：doctor / run；--dry-run 仅显示计划，不调用接口、不写数据。"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from automation.doctor import inspect
from automation.runner import STAGES, COMBINED_STAGES, plan, run
from manus_source.window import latest_cutoff_date, ten_am_window

ROOT = Path(__file__).resolve().parents[1]


def valid_date(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
        return value
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期格式必须为 YYYY-MM-DD") from exc


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "run"))
    parser.add_argument("--date", type=valid_date,
                        help="固定24小时模式为窗口结束日；旧自然日模式为采集日")
    parser.add_argument("--window-mode", choices=("ten-am", "calendar-day"), default="ten-am")
    parser.add_argument('--cutoff-time', default='09:30', help='北京时间固定24小时窗口结束时刻 HH:MM，默认09:30')
    parser.add_argument("--stage", choices=("all", *STAGES), default="all")
    parser.add_argument("--source-mode", choices=("full", "aihot-only"), default="full",
                        help="full 并行采集 AIHOT/Manus；aihot-only 只关闭 Manus，保留模型与公司库更新")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-promote", action="store_true", help="执行接口并生成候选产物，保留正式数据")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不调用任何外部接口")
    parser.add_argument("--skip-search", action="store_true", help="跳过可选 Tavily 搜索")
    parser.add_argument("--manus-credit-limit", type=int, default=20,
                        help="full 模式每个 Manus 来源的观察止损线，范围 10-60（默认 20）")
    args = parser.parse_args(argv)
    from manus_source.window import cutoff_time
    os.environ['AIHOT_CUTOFF_TIME'] = args.cutoff_time
    try:
        cutoff_time()
    except ValueError:
        parser.error('--cutoff-time 必须为有效 HH:MM')
    ten_am = args.window_mode == "ten-am"
    args.date = args.date or (latest_cutoff_date() if ten_am else
                             (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)).isoformat())
    if args.source_mode == "aihot-only" and args.stage not in ("all", "snapshot"):
        parser.error("aihot-only 只支持 all（统一模型与公司更新）或旧 snapshot 调试阶段")
    if not 10 <= args.manus_credit_limit <= 60:
        parser.error("--manus-credit-limit 必须在 10-60 credits 之间")
    combined = args.stage == 'all'
    if combined and not ten_am:
        parser.error('统一采集使用固定24小时窗口；自然日仅供旧单阶段调试')
    stages = list(COMBINED_STAGES) if combined else [args.stage]
    if combined and args.source_mode == 'aihot-only':
        stages = [s for s in stages if s not in ('discovery', 'content')]
    if args.dry_run:
        run_path = ROOT / "work" / "runs" / args.date
        if ten_am:
            run_path = run_path / "ten-am"
        commands = plan(ROOT, run_path / "<run-id>" / "workspace",
                        args.date, args.resume, args.skip_search, ten_am=ten_am,
                        source_mode=args.source_mode, manus_credit_limit=args.manus_credit_limit, combined=combined)
        print(json.dumps({"date": args.date, "publish": not args.no_promote,
                          "sourceMode": args.source_mode,
                          "parallelCollectors": ['aihot', 'discovery'] if combined and args.source_mode == 'full' else ['aihot'] if combined else [],
                          "collectionWindow": ten_am_window(args.date) if ten_am else None,
                          "stages": [{"stage": s, "command": commands[s]} for s in stages]},
                         ensure_ascii=False, indent=2))
        return 0
    check_stages = [s for s in stages if s not in ('discovery', 'content')] if combined and args.source_mode == 'aihot-only' else stages
    checks = inspect(ROOT, check_stages, args.date, ten_am=ten_am,
                     require_llm=combined or args.source_mode != "aihot-only")
    for result in checks:
        print(f"[{'OK' if result['ok'] else 'MISSING'}] {result['check']}: {result['detail']}")
    # Missing Manus credentials disable only that collector, not the shared model.
    branch_checks = {'MANUS_API_KEY', 'trafilatura', '正文模式', 'scripts/prompts/manus_content.md',
                     'scripts/prompts/manus_discovery_window.md'}
    if any(not c["ok"] and not (combined and c['check'] in branch_checks) for c in checks):
        return 1
    if args.command == "doctor":
        return 0
    try:
        return run(ROOT, args.date, stages, resume=args.resume, no_promote=args.no_promote,
                   skip_search=args.skip_search, ten_am=ten_am, source_mode=args.source_mode,
                   manus_credit_limit=args.manus_credit_limit, combined=combined)
    except ValueError as exc:
        print(f"运行检查失败：{exc}", file=sys.stderr)
        return 1
    except FileExistsError:
        print("已有运行锁 work/pipeline.lock；确认没有执行中的任务后再处理残留锁。", file=sys.stderr)
        return 1
    except (OSError, KeyError):
        print("运行文件缺失或不可写，请检查 work/runs 下的状态和磁盘权限。", file=sys.stderr)
        return 1


def main(argv=None):
    previous = os.environ.get('AIHOT_CUTOFF_TIME')
    try:
        return _main(argv)
    finally:
        if previous is None:
            os.environ.pop('AIHOT_CUTOFF_TIME', None)
        else:
            os.environ['AIHOT_CUTOFF_TIME'] = previous


if __name__ == "__main__":
    sys.exit(main())
