"""只读调度诊断；不触发任务，不修改采集窗口或失败策略。"""
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BJ = ZoneInfo('Asia/Shanghai')


def timing_report(run):
    created = datetime.fromisoformat(run['created_at'].replace('Z', '+00:00')).astimezone(BJ)
    report = {'event': run['event'], 'createdAtBeijing': created.isoformat(),
              'checkedAtBeijing': datetime.now(BJ).isoformat()}
    if run['event'] == 'schedule':
        # GitHub未提供原定触发时间戳；以记录创建日09:30比较，不推断跨日丢失次数。
        expected = created.replace(hour=9, minute=30, second=0, microsecond=0)
        report.update(expectedSameDayBeijing=expected.isoformat(),
                      delaySeconds=(created-expected).total_seconds())
    return report


def main():
    try:
        url = (f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}"
               f"/actions/runs/{os.environ['GITHUB_RUN_ID']}")
        request = Request(url, headers={'Authorization': 'Bearer '+os.environ['GITHUB_TOKEN'],
                                       'Accept': 'application/vnd.github+json',
                                       'User-Agent': 'AI-HOT-schedule-audit'})
        with urlopen(request, timeout=15) as response:
            report = timing_report(json.load(response))
        lines = ['### 调度时间核对（北京时间）',
                 f"- 触发类型：{report['event']}",
                 f"- GitHub 创建运行：{report['createdAtBeijing']}",
                 f"- 进入诊断步骤：{report['checkedAtBeijing']}"]
        if 'delaySeconds' in report:
            minutes = report['delaySeconds']/60
            lines += [f"- 创建日计划时刻：{report['expectedSameDayBeijing']}",
                      f'- 相对该时刻偏差：{minutes:.1f} 分钟（正数为晚）']
            if minutes > 15:
                print(f'::warning::GitHub schedule 创建比当日北京时间09:30晚 {minutes:.1f} 分钟；采集窗口不变。')
        print(json.dumps(report, ensure_ascii=False))
    except Exception as error:
        # 不输出请求对象、凭据或响应正文；诊断失败不能阻断正式采集。
        lines = [f'调度诊断不可用（{type(error).__name__}），请检查 GitHub 运行时间。']
        print('::warning::调度诊断不可用，继续既有采集流程。')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf8') as stream:
            stream.write('\n'.join(lines)+'\n')


if __name__ == '__main__':
    main()
