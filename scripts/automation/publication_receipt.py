"""Record a successful git push and dispatch acknowledgement, never deployment."""
import argparse
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from .publish import save

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = 'work/publication-receipt.json'
PUBLIC_FILES = ('web/public/snapshot.json', 'web/public/company-overview.json',
                'web/public/funding-table.json', 'web/public/company-profile-review.json')


def write_receipt(root, data_sha, dispatch_status):
    if not re.fullmatch(r'[0-9a-f]{40}', data_sha):
        raise ValueError('invalid pushed commit SHA')
    if dispatch_status not in ('pending', 'accepted', 'failed'):
        raise ValueError('invalid Pages dispatch status')
    root = Path(root)
    now = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    code_sha = os.getenv('GITHUB_SHA', '')
    # These are provenance labels only; never copy arbitrary environment values.
    run_id, attempt = os.getenv('GITHUB_RUN_ID', ''), os.getenv('GITHUB_RUN_ATTEMPT', '')
    receipt = {'schemaVersion': 1, 'recordedAt': now, 'pushSucceeded': True,
        'githubRunId': run_id if run_id.isdigit() else None,
        'githubRunAttempt': int(attempt) if attempt.isdigit() else None,
        'codeSha': code_sha if re.fullmatch(r'[0-9a-f]{40}', code_sha) else None,
        'dataCommitSha': data_sha,
        'pagesDispatch': {'workflow': 'deploy-pages.yml', 'ref': 'main', 'status': dispatch_status,
                          'basis': 'gh_workflow_run_exit_status', 'deploymentVerified': False},
        'publicFileSha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                             for name in PUBLIC_FILES if (root / name).is_file()}}
    if 'web/public/company-profile-review.json' in receipt['publicFileSha256']:
        receipt['manualReviewEvidence'] = {'path': 'web/public/company-profile-review.json',
            'mayBeHistorical': True, 'provesCurrentDailyResearch': False}
    save(root / OUTPUT, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-sha', required=True)
    parser.add_argument('--pages-dispatch', required=True, choices=('pending', 'accepted', 'failed'))
    args = parser.parse_args()
    try:
        write_receipt(ROOT, args.data_sha, args.pages_dispatch)
    except (OSError, ValueError) as error:
        print('发布回执写入失败：' + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
