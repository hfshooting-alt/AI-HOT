"""Fail-closed daily cloud lease; GitHub cache alone is not a durable counter.

The history guard assumes this repository's serial fetch workflow and retained
run history. It does not guarantee a global limit after administrative deletion
of history, or across repositories/local environments. No private data is cached.
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo


LIMITS = {'entities': 5, 'pages': 10, 'requests': 5}
BJ = ZoneInfo('Asia/Shanghai')
MAX_PAGES = 20


def today_bj():
    return datetime.now(BJ).date().isoformat()


def _context(day, owner):
    if not isinstance(day, str) or day != today_bj():
        raise ValueError('research_lease_day_changed')
    if not isinstance(owner, str) or not re.fullmatch(r'(?:[1-9][0-9]*|local):[1-9][0-9]*', owner):
        raise ValueError('research_lease_invalid_owner')
    if os.getenv('GITHUB_ACTIONS'):
        actual = os.getenv('GITHUB_RUN_ID', '') + ':' + os.getenv('GITHUB_RUN_ATTEMPT', '')
        if owner != actual or owner.startswith('local:'):
            raise ValueError('research_lease_owner_mismatch')


def _valid(value, day, owner):
    return (isinstance(value, dict)
            and set(value) == {'schemaVersion', 'day', 'owner', 'limits', 'status'}
            and type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['day'] == day and value['owner'] == owner
            and value['status'] == 'reserved' and value['limits'] == LIMITS
            and all(type(v) is int for v in value['limits'].values()))


def check(directory, day, owner):
    """Validate a read-back lease locally; READY is checked by the consumer."""
    try:
        _context(day, owner)
        path = Path(directory) / 'lease.json'
        if path.is_symlink():
            return False
        return _valid(json.loads(path.read_text(encoding='utf-8')), day, owner)
    except (ValueError, OSError, TypeError, KeyError):
        return False


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get_page(url, token):
    """Read only the fixed GitHub API endpoint; never expose response bodies."""
    try:
        request = Request(url, headers={'Accept': 'application/vnd.github+json',
            'Authorization': 'Bearer ' + token, 'X-GitHub-Api-Version': '2022-11-28'})
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError('oversized')
            return json.loads(raw), response.headers.get('Link', '')
    except Exception:
        raise ValueError('research_lease_history_unavailable') from None


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('research_lease_history_invalid')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('missing_zone')
        return result
    except ValueError:
        raise ValueError('research_lease_history_invalid') from None


def _history_guard(day, owner):
    run_id, attempt = owner.split(':')
    if attempt != '1':
        raise ValueError('research_lease_rerun_without_cache')
    repo, token = os.getenv('GITHUB_REPOSITORY', ''), os.getenv('GITHUB_TOKEN', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or not token:
        raise ValueError('research_lease_history_unavailable')
    start = datetime.fromisoformat(day).replace(tzinfo=BJ)
    end = start + timedelta(days=1)
    endpoint = f'https://api.github.com/repos/{repo}/actions/workflows/fetch-manus.yml/runs'
    runs, total, current = set(), None, False
    # Do not filter by created: a queued or rerun workflow may execute on a
    # different Beijing day from its creation. Inspect every retained run.
    for page in range(1, MAX_PAGES + 1):
        url = endpoint + '?' + urlencode({'per_page': 100, 'page': page})
        payload, link = _get_page(url, token)
        if not isinstance(payload, dict) or type(payload.get('total_count')) is not int:
            raise ValueError('research_lease_history_invalid')
        if total is None:
            total = payload['total_count']
        entries = payload.get('workflow_runs')
        if total < 1 or total != payload['total_count'] or not isinstance(entries, list) or len(entries) > 100:
            raise ValueError('research_lease_history_incomplete')
        for run in entries:
            if (not isinstance(run, dict) or type(run.get('id')) is not int
                    or run['id'] <= 0 or run['id'] in runs):
                raise ValueError('research_lease_history_invalid')
            runs.add(run['id'])
            created, updated = _timestamp(run.get('created_at')), _timestamp(run.get('updated_at'))
            started = _timestamp(run['run_started_at']) if run.get('run_started_at') else created
            if updated < created or started < created or type(run.get('run_attempt')) is not int:
                raise ValueError('research_lease_history_invalid')
            if str(run['id']) == run_id:
                if run['run_attempt'] != 1:
                    raise ValueError('research_lease_history_invalid')
                current = True
                continue
            # updated_at can overestimate the end time, deliberately reserving
            # too much. Pending older runs also cannot prove an unused day.
            if (created < end and (updated >= start or started >= start
                    or run.get('status') != 'completed')):
                raise ValueError('research_lease_day_already_used')
        if not isinstance(link, str):
            raise ValueError('research_lease_history_invalid')
        next_links = re.findall(r'<([^>]+)>;\s*rel="next"', link)
        if next_links:
            following = urlsplit(next_links[0])
            if (len(next_links) != 1 or not entries
                    or following._replace(query='', fragment='').geturl() != endpoint
                    or following.fragment
                    or parse_qs(following.query) != {'per_page': ['100'], 'page': [str(page + 1)]}):
                raise ValueError('research_lease_history_incomplete')
        elif len(runs) == total and current:
            return
        else:
            raise ValueError('research_lease_history_incomplete')
    raise ValueError('research_lease_history_incomplete')


def reserve(directory, day, owner):
    """Reserve a whole daily batch once, with no overwrite and no API retry."""
    _context(day, owner)
    directory = Path(directory)
    path = directory / 'lease.json'
    if path.exists() or path.is_symlink():
        if not check(directory, day, owner):
            raise ValueError('research_lease_existing_invalid_or_other_owner')
        return json.loads(path.read_text(encoding='utf-8'))
    if os.getenv('GITHUB_ACTIONS'):
        _history_guard(day, owner)
    value = {'schemaVersion': 1, 'day': day, 'owner': owner,
             'limits': dict(LIMITS), 'status': 'reserved'}
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise ValueError('research_lease_cannot_reserve') from None
    return value
