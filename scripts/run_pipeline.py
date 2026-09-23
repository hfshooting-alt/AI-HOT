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
from automation.runner import STAGES, COMBINED_STAGES, DIRECT_STAGES, plan, run, normalize_source_mode
from manus_source.window import latest_cutoff_date, ten_am_window, timestamp

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
    parser.add_argument("command", choices=("doctor", "run", "review-candidate", "publish-candidate"))
    parser.add_argument('--candidate', type=Path, help='review时传候选workspace；publish时传审核目录')
    parser.add_argument("--date", type=valid_date,
                        help="固定24小时模式为窗口结束日；旧自然日模式为采集日")
    parser.add_argument("--window-mode", choices=("rolling-24h", "ten-am", "calendar-day"), default="rolling-24h")
    parser.add_argument('--window-end', help='固定扫描开始时刻，含时区的 ISO 时间；默认取当前北京时间到秒')
    parser.add_argument('--cutoff-time', default='09:30', help='北京时间固定24小时窗口结束时刻 HH:MM，默认09:30')
    parser.add_argument("--stage", choices=("all", *STAGES), default="all")
    parser.add_argument("--source-mode", choices=("manus-only", "direct-only", "full", "aihot-only"), default="manus-only",
                        help="Manus 或匿名媒体页面直采；full 为 Manus 兼容别名，AIHOT 已停用")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-promote", action="store_true", help="执行接口并生成候选产物，保留正式数据")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不调用任何外部接口")
    parser.add_argument("--skip-search", action="store_true", help="跳过可选 Tavily 搜索")
    parser.add_argument("--manus-credit-limit", type=int, default=20,
                        help="每来源观察止损线 10-60，默认20；显式0取消该观察线（非服务端费用上限）")
    args = parser.parse_args(argv)
    if args.window_end:
        try:
            end = timestamp(args.window_end)
            existing = os.environ.get('NEWS_COLLECTION_END')
            if existing and timestamp(existing) != end:
                raise ValueError('--window-end 与 NEWS_COLLECTION_END 不一致')
            os.environ['NEWS_COLLECTION_END'] = args.window_end
        except ValueError as exc:
            parser.error(str(exc))
    if args.command in ('review-candidate', 'publish-candidate'):
        if not args.candidate or args.dry_run or args.resume:
            parser.error('候选命令要求--candidate，且不接受--dry-run或--resume')
        from automation.candidate import prepare, promote
        from manus_source.window import cutoff_time
        os.environ['AIHOT_CUTOFF_TIME'] = args.cutoff_time
        try:
            cutoff_time()
            if args.command == 'review-candidate':
                directory, summary = prepare(ROOT, args.candidate)
                print(json.dumps({'reviewDirectory': str(directory), **summary}, ensure_ascii=False))
            else:
                print(json.dumps(promote(ROOT, args.candidate), ensure_ascii=False))
            return 0
        except (OSError, ValueError, KeyError) as exc:
            print(f'候选检查未通过：{exc}', file=sys.stderr)
            return 1
    from manus_source.window import cutoff_time
    os.environ['AIHOT_CUTOFF_TIME'] = args.cutoff_time
    try:
        cutoff_time()
    except ValueError:
        parser.error('--cutoff-time 必须为有效 HH:MM')
    try:
        args.source_mode = normalize_source_mode(args.source_mode)
    except ValueError as exc:
        parser.error(str(exc))
    ten_am = args.window_mode != 'calendar-day'
    if args.window_mode == 'rolling-24h':
        try:
            if args.resume:
                # Resume restores the original window before planning any call.
                day = args.date
                if not day and os.environ.get('NEWS_COLLECTION_END'):
                    day = timestamp(os.environ['NEWS_COLLECTION_END']).date().isoformat()
                if not day:
                    parser.error('--resume 需要原运行 --date 或 NEWS_COLLECTION_END')
                runs = ROOT / 'work/runs' / day / 'ten-am'
                run_id = json.loads((runs / 'latest.json').read_text(encoding='utf-8'))['runId']
                if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
                    raise ValueError('原运行标识不合法')
                saved = json.loads((runs / run_id / 'state.json').read_text(encoding='utf-8'))['collectionWindow']
                existing = os.environ.get('NEWS_COLLECTION_END')
                if existing and timestamp(existing) != timestamp(saved['end']):
                    raise ValueError('恢复窗口与原运行不一致')
                os.environ['NEWS_COLLECTION_END'] = saved['end']
            else:
                os.environ.setdefault('NEWS_COLLECTION_END', datetime.now(ZoneInfo('Asia/Shanghai')).replace(microsecond=0).isoformat())
            end = timestamp(os.environ['NEWS_COLLECTION_END'])
            if args.date and args.date != end.date().isoformat():
                raise ValueError('--date 与扫描窗口结束日不一致；历史固定窗口请显式 --window-mode ten-am')
            args.date = end.date().isoformat()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
    args.date = args.date or (latest_cutoff_date() if ten_am else
                             (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)).isoformat())
    if args.manus_credit_limit != 0 and not 10 <= args.manus_credit_limit <= 60:
        parser.error("--manus-credit-limit 必须为0或10-60 credits")
    combined = args.stage == 'all'
    if combined and not ten_am:
        parser.error('统一采集使用固定24小时窗口；自然日仅供旧单阶段调试')
    if args.source_mode == 'direct-only' and not combined:
        parser.error('direct-only 使用完整隔离批次 --stage all')
    stages = list(DIRECT_STAGES if args.source_mode == 'direct-only' else COMBINED_STAGES) if combined else [args.stage]
    if args.dry_run:
        run_path = ROOT / "work" / "runs" / args.date
        if ten_am:
            run_path = run_path / "ten-am"
        commands = plan(ROOT, run_path / "<run-id>" / "workspace",
                        args.date, args.resume, args.skip_search, ten_am=ten_am,
                        source_mode=args.source_mode, manus_credit_limit=args.manus_credit_limit, combined=combined)
        print(json.dumps({"date": args.date, "publish": not args.no_promote,
                          "sourceMode": args.source_mode,
                          "parallelCollectors": ['direct' if args.source_mode == 'direct-only' else 'discovery'] if combined else [],
                          "contentMode": "script",
                          "collectionWindow": ten_am_window(args.date) if ten_am else None,
                          "stages": [{"stage": s, "command": commands[s]} for s in stages]},
                         ensure_ascii=False, indent=2))
        return 0
    checks = inspect(ROOT, stages, args.date, ten_am=ten_am, require_llm=True)
    for result in checks:
        print(f"[{'OK' if result['ok'] else 'MISSING'}] {result['check']}: {result['detail']}")
    if any(not c["ok"] for c in checks):
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
    previous = {key: os.environ.get(key) for key in ('AIHOT_CUTOFF_TIME', 'NEWS_COLLECTION_END', 'MANUS_CONTENT_MODE')}
    os.environ['MANUS_CONTENT_MODE'] = 'script'
    try:
        return _main(argv)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    sys.exit(main())
