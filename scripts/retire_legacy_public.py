"""Retire legacy public pages in an isolated work/ candidate, without publishing.

Plan by default; --apply removes only the listed candidate files. Published
news/company/funding JSON is never rewritten here. Validate those contents via
the normal candidate review before promotion. No network or model calls.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = frozenset({'snapshot.json', 'company-overview.json', 'funding-table.json', 'favicon.svg'})
OPTIONAL = frozenset({'publication-receipt.json', 'pipeline-status.json'})
RETIRED_FILES = frozenset({
    'company-enrichment.html', 'company-research-review.html',
    'company-profile-review.json', 'company-research-review.json',
    'reviewed-news.json', 'reviewed-news-report.json',
    'manus-supplement-20260922.json', 'manus-supplement-report.json',
    'file.svg', 'globe.svg', 'window.svg',
})
RETIRED_DIRS = frozenset({'history', 'weekly'})
AUDIT_NAME = 'retired-public-audit.json'


def _is_link(path):
    info = path.lstat()
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def _within(path, boundary):
    if not path.resolve().is_relative_to(boundary.resolve()):
        raise ValueError('Candidate path escapes its allowed workspace')
    if _is_link(path):
        raise ValueError('Candidate links/junctions are not allowed')


def _workspace(path):
    raw = Path(os.path.abspath(path))
    work = ROOT / 'work'
    if not raw.is_relative_to(work) or raw == work:
        raise ValueError('Only isolated candidate workspaces under project work/ are accepted')
    for parent in (raw, *raw.parents):
        if parent == ROOT:
            break
        if _is_link(parent):
            raise ValueError('Candidate links/junctions are not allowed')
    workspace = raw.resolve()
    if not workspace.is_relative_to(work.resolve()) or not workspace.is_dir():
        raise ValueError('Candidate workspace is missing or outside work/')
    public = workspace / 'web/public'
    for path in (workspace / 'data', workspace / 'web', public):
        _within(path, workspace)
        if not path.is_dir():
            raise ValueError('Expected a complete candidate workspace with data/ and web/public/')
    return workspace, public


def _public_files(public):
    files, directories = [], []
    pending = [public]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            _within(path, public)
            if path.is_dir():
                directories.append(path)
                pending.append(path)
            elif path.is_file():
                files.append(path)
            else:
                raise ValueError('Unsupported public filesystem entry')
    return files, directories


def _explicit_keeps(values):
    result = set()
    for value in values:
        path = PurePosixPath(value)
        if (not value or '\\' in value or path.is_absolute() or '..' in path.parts
                or path.suffix != '.json' or path.as_posix() != value
                or path.parts[0] in RETIRED_DIRS or value in RETIRED_FILES):
            raise ValueError('--keep accepts only an explicit non-retired relative JSON path')
        result.add(value)
    return result


def _fingerprint(path, public):
    return {'path': path.relative_to(public).as_posix(), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _save_audit(workspace, report):
    target = workspace / AUDIT_NAME
    temp = workspace / (AUDIT_NAME + '.tmp')
    for path in (target, temp):
        if path.exists() or path.is_symlink():
            _within(path, workspace)
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, target)


def retire(workspace, *, apply=False, keep=()):
    workspace, public = _workspace(workspace)
    extra = _explicit_keeps(keep)
    files, directories = _public_files(public)
    names = {path.relative_to(public).as_posix() for path in files}
    if REQUIRED - names:
        raise ValueError('Missing required public files: ' + ', '.join(sorted(REQUIRED - names)))
    if extra - names:
        raise ValueError('Explicit --keep file does not exist: ' + ', '.join(sorted(extra - names)))
    retained, removed, unknown = [], [], []
    for path in files:
        relative = path.relative_to(public).as_posix()
        if relative in REQUIRED | OPTIONAL | extra:
            retained.append(_fingerprint(path, public))
        elif (relative in RETIRED_FILES or path.relative_to(public).parts[0] in RETIRED_DIRS
              or path.suffix.lower() == '.html'):
            removed.append(_fingerprint(path, public))
        else:
            unknown.append(relative)
    if unknown:
        raise ValueError('Unreviewed public files; review and explicitly --keep JSON if needed: '
                         + ', '.join(sorted(unknown)))
    # Parse the retained JSON without treating it as verified publication data.
    for row in retained:
        if row['path'].endswith('.json'):
            json.loads((public / row['path']).read_text(encoding='utf-8-sig'))
    report = {'schemaVersion': 1, 'workspace': str(workspace),
              'recordedAt': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
              'mode': 'apply' if apply else 'plan', 'status': 'planned',
              'retained': retained, 'retire': removed, 'explicitKeeps': sorted(extra),
              'deleted': [], 'published': False, 'newHttpCalls': 0, 'newModelCalls': 0,
              'requiresCandidateContentValidation': True,
              'navigationNote': 'Caller must rebuild/remove retired history/weekly navigation references; required JSON is untouched.'}
    _save_audit(workspace, report)
    if not apply:
        return report
    try:
        # Validate every planned path/hash before deleting any candidate file.
        for row in retained + removed:
            path = public / row['path']
            _within(path, public)
            if _fingerprint(path, public) != row:
                raise ValueError('Public candidate changed after planning')
        for row in removed:
            path = public / row['path']
            _within(path, public)
            path.unlink()
            report['deleted'].append(row['path'])
        for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            if path.relative_to(public).parts[0] in RETIRED_DIRS:
                _within(path, public)
                path.rmdir()
        report['status'] = 'complete'
    except Exception as error:
        report['status'] = 'incomplete'
        report['errorType'] = type(error).__name__
        _save_audit(workspace, report)
        raise
    _save_audit(workspace, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Remove listed files from this private candidate only')
    parser.add_argument('--keep', action='append', default=[], metavar='RELATIVE.json',
                        help='Explicitly retain one reviewed non-retired public JSON; repeat as needed')
    args = parser.parse_args(argv)
    try:
        report = retire(args.workspace, apply=args.apply, keep=args.keep)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Public retirement rejected: {error}\n')
    print(json.dumps({'mode': report['mode'], 'status': report['status'],
                      'retained': len(report['retained']), 'retired': len(report['deleted']),
                      'planned': len(report['retire']), 'audit': str(args.workspace / AUDIT_NAME)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
