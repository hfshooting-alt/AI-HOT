"""Persist numeric cost and stop diagnostics, excluding prompts, bodies and errors."""
import json
from pathlib import Path


def summarize(root):
    costs, stops = [], []
    numeric = ('sourceCount', 'creditLimitPerSource', 'maxObservedRunCredits',
               'balanceBefore', 'balanceAfter', 'creditsUsed', 'sourceFailures')
    for path in sorted(root.glob('**/cost-report.json')):
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(row, dict):
                continue
            costs.append({k: row[k] for k in numeric if type(row.get(k)) in (int, float)})
        except (OSError, ValueError):
            continue
    for path in sorted(root.glob('**/diagnostics/*.json')):
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(row, dict):
                continue
            stops.append({'taskId': row.get('taskId'),
                          'stopSucceeded': row.get('stopSucceeded') is True})
        except (OSError, ValueError):
            continue
    return {'costReports': costs, 'taskStops': stops}


if __name__ == '__main__':
    output = Path('work/diagnostic-summary.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summarize(Path('work')), indent=2), encoding='utf-8')
