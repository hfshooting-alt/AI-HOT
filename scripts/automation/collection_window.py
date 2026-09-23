"""Freeze the scheduled collection window from this GitHub run's creation time."""
from datetime import timedelta
import json
import os
from pathlib import Path

from automation.schedule_audit import ROOT, bj_time


def scheduled_end(report, environ):
    """Use the latest elapsed Beijing cutoff, never the runner's wall clock."""
    if report.get('status') != 'available' or report.get('event') != 'schedule':
        raise ValueError('缺少定时运行创建时间，停止采集以免扫描错误窗口')
    for field, variable in (('runId', 'GITHUB_RUN_ID'), ('runAttempt', 'GITHUB_RUN_ATTEMPT'),
                            ('headSha', 'GITHUB_SHA')):
        if not environ.get(variable) or str(report.get(field)) != environ[variable]:
            raise ValueError('调度记录不属于当前运行，不能用于确定采集窗口')
    created = bj_time(report['createdAtBeijing'])
    end = created.replace(hour=9, minute=30, second=0, microsecond=0)
    if end > created:
        end -= timedelta(days=1)
    return end


def main(root=ROOT, environ=None):
    environ = os.environ if environ is None else environ
    if environ.get('GITHUB_EVENT_NAME') != 'schedule':
        return 0  # Manual runs continue to freeze their own rolling 24-hour window.
    try:
        report = json.loads((Path(root) / 'work/schedule-audit.json').read_text(encoding='utf-8'))
        end = scheduled_end(report, environ)
        start = end - timedelta(days=1)
        with Path(environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
            stream.write(f'date={end.date().isoformat()}\nwindow_end={end.isoformat()}\n')
        summary = (f'定时采集窗口（北京时间）：[{start.isoformat()}, {end.isoformat()})；'
                   '依据当前运行创建时间，排队或重新执行不移动窗口。')
        print(summary)
        if environ.get('GITHUB_STEP_SUMMARY'):
            with Path(environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
                stream.write(summary + '\n')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print('::error::无法确认当前定时运行的北京时间窗口；未开始采集，请检查 schedule-audit.json。')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
