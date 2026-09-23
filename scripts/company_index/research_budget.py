"""Private durable reservations and successful replay for optional daily research."""
import argparse
import copy
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from llm_failures import LLMRequestError
from .config import now_bj_iso
from .research import cached_proposal, proposal_key

DEFAULT_BUDGET_DIR = Path(__file__).resolve().parents[2] / 'work' / 'company-research-budget'
LIMITS = {'entities': 5, 'pages': 10, 'requests': 5}


class BudgetUnavailable(RuntimeError):
    """An allowlisted diagnostic, never an underlying exception payload."""


def beijing_day(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo('Asia/Shanghai'))).astimezone(
            ZoneInfo('Asia/Shanghai')).date().isoformat()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ResearchBudget:
    def __init__(self, directory=None, *, clock=now_bj_iso, limits=LIMITS, require_cloud_lease=True):
        self.directory = Path(directory) if directory is not None else DEFAULT_BUDGET_DIR
        self.clock = clock
        self.day = beijing_day(clock())
        self.owner = os.getenv('GITHUB_RUN_ID', '') + ':' + os.getenv('GITHUB_RUN_ATTEMPT', '')
        self.cloud = bool(os.getenv('GITHUB_ACTIONS'))
        # Explicit full review retains durable input/request reservations while
        # replacing the legacy daily financial quota with a finite input pool.
        self.limits = copy.deepcopy(limits)
        self.require_cloud_lease = require_cloud_lease
        self.path = self.directory / 'ledger.json'

    @contextmanager
    def journal(self, *, write=True):
        """Short exclusive transactions; stale/contended locks fail closed."""
        lock = self.directory / 'ledger.lock'
        acquired = False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            acquired = True
            os.close(fd)
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if (not isinstance(data, dict) or data.get('schemaVersion') != 1
                        or not all(isinstance(data.get(k), dict) for k in ('inputs', 'requests'))):
                    raise BudgetUnavailable('ledger_invalid')
            else:
                data = {'schemaVersion': 1, 'inputs': {}, 'requests': {}}
            yield data
            if write:
                atomic_json(self.path, data)
        except BudgetUnavailable:
            raise
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise BudgetUnavailable('ledger_unavailable') from error
        finally:
            if acquired:
                try:
                    lock.unlink(missing_ok=True)
                except OSError:
                    pass  # A stale lock keeps subsequent work fail closed.

    def permission(self):
        if self.day is None or beijing_day(self.clock()) != self.day:
            return 'day_changed'
        if self.cloud and self.require_cloud_lease:
            if os.getenv('COMPANY_RESEARCH_BUDGET_READY') != '1':
                return 'cloud_budget_not_ready'
            from .cloud_research_lease import check
            if not check(self.directory, self.day, self.owner):
                return 'cloud_lease_unavailable'
        return None

    @staticmethod
    def _usage(data, day):
        usage = dict.fromkeys(LIMITS, 0)
        for entry in data['inputs'].values():
            if not isinstance(entry, dict):
                raise BudgetUnavailable('ledger_invalid')
            if entry.get('day') is not None and beijing_day(entry['day']) != entry['day']:
                raise BudgetUnavailable('ledger_invalid')
            if not isinstance(entry.get('event'), dict):
                raise BudgetUnavailable('ledger_invalid')
            if entry.get('day') not in (None, day):
                continue
            units = entry.get('units')
            if (not isinstance(units, dict) or any(type(units.get(k)) is not int
                    or units[k] < 0 for k in LIMITS)):
                raise BudgetUnavailable('ledger_invalid')
            for kind in LIMITS:
                usage[kind] += units[kind]
        return usage

    def synchronize(self, state):
        # Import each published legacy attempt once; the private ledger wins
        # thereafter, including after a failed publication or a new run folder.
        with self.journal() as data:
            for key, event in state.items():
                if key in data['inputs']:
                    continue
                event = event if isinstance(event, dict) else {}
                urls = event.get('urls')
                data['inputs'][key] = {'day': beijing_day(event.get('checkedAt')),
                    'event': copy.deepcopy(event), 'legacy': True,
                    'units': {'entities': 1, 'pages': min(len(urls), 2) if isinstance(urls, list) else 2,
                        'requests': int(event.get('modelAttempted') is not False
                                        and event.get('status') != 'no_readable_page')}}
            return copy.deepcopy(data)

    def usage(self):
        with self.journal(write=False) as data:
            return self._usage(data, self.day)

    def snapshot(self):
        with self.journal(write=False) as data:
            return copy.deepcopy(data)

    def lookup(self, key):
        with self.journal(write=False) as data:
            entry = copy.deepcopy(data['inputs'].get(key))
        if entry is None:
            return None
        request = entry.get('requestKey')
        if request:
            saved = self.directory / 'results' / f'{request}.json'
            if saved.exists():
                try:
                    item = json.loads(saved.read_text(encoding='utf-8'))
                    if not isinstance(item['proposal']['facts'], list):
                        raise ValueError()
                    entry.update(proposal=item['proposal'], proposalCheckedAt=item['checkedAt'])
                except (OSError, ValueError, TypeError, KeyError) as error:
                    raise BudgetUnavailable('result_invalid') from error
            elif entry.get('cacheDay'):
                # A model result may be durable before the enclosing event is
                # finalized. Recover that success without another request.
                try:
                    proposal = cached_proposal(self.directory / 'model-cache' / entry['cacheDay'], request)
                except (OSError, ValueError, TypeError) as error:
                    raise BudgetUnavailable('result_invalid') from error
                if proposal is not None:
                    entry.update(proposal=proposal, proposalCheckedAt=entry['event']['checkedAt'])
        return entry

    def begin(self, key, event):
        with self.journal() as data:
            if key in data['inputs']:
                return 'already_attempted'
            reason = self.permission()
            if reason:
                return reason
            usage = self._usage(data, self.day)
            count = len(event['urls'])
            if self.limits is not None and (usage['entities'] >= self.limits['entities']
                    or usage['requests'] >= self.limits['requests']
                    or usage['pages'] + count > self.limits['pages']):
                return 'daily_limit'
            data['inputs'][key] = {'day': self.day, 'event': copy.deepcopy(event),
                'units': {'entities': 1, 'pages': count, 'requests': 0}}
        return None

    def finish(self, key, event):
        with self.journal() as data:
            data['inputs'][key]['event'] = copy.deepcopy(event)

    def run_proposal(self, key, tx, packet, fn, previous_directory, *, max_requests, full_review=False):
        if self.limits is None and not full_review:
            raise BudgetUnavailable('full_review_required')
        request = proposal_key(tx, packet, isolate_invalid=True)
        destination = self.directory / 'model-cache' / self.day
        saved = self.directory / 'results' / f'{request}.json'
        attempted = False
        with self.journal() as data:
            entry = data['inputs'][key]
            checked_at = entry['event']['checkedAt']
            cached = None
            if saved.exists():
                item = json.loads(saved.read_text(encoding='utf-8'))
                cached, checked_at = item['proposal'], item['checkedAt']
            else:
                for path in (destination, Path(previous_directory)):
                    cached = cached_proposal(path, request)
                    if cached is not None:
                        break
            entry.update(requestKey=request, cacheDay=self.day)
            if cached is None:
                if request in data['requests']:
                    raise BudgetUnavailable('request_already_attempted')
                reason = self.permission()
                if reason:
                    raise BudgetUnavailable(reason)
                if (self.limits is not None
                        and self._usage(data, self.day)['requests'] >= self.limits['requests']):
                    raise BudgetUnavailable('daily_limit')
                entry['units']['requests'] += 1
                entry['event']['modelAttempted'] = True
                data['requests'][request] = {'day': self.day, 'inputKey': key, 'status': 'reserved'}
                attempted = True
        if cached is None:
            # The reservation is committed before entering arbitrary model code.
            cached = fn(tx, packet, destination, allow_paid=True,
                        max_requests=None if self.limits is None else self.limits['requests'],
                        isolate_invalid=True, **({'full_review': True} if full_review else {}))
        if not isinstance(cached, dict) or not isinstance(cached.get('facts'), list):
            raise LLMRequestError('invalid_response')
        atomic_json(saved, {'proposal': cached, 'checkedAt': checked_at})
        with self.journal() as data:
            if request in data['requests']:
                data['requests'][request]['status'] = 'completed'
        return cached, attempted, checked_at


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--reserve', action='store_true')
    action.add_argument('--check', action='store_true')
    parser.add_argument('--day', required=True)
    parser.add_argument('--directory', type=Path, default=DEFAULT_BUDGET_DIR)
    parser.add_argument('--owner', default=os.getenv('GITHUB_RUN_ID', 'local') + ':' + os.getenv('GITHUB_RUN_ATTEMPT', '1'))
    args = parser.parse_args()
    from .cloud_research_lease import reserve, check
    try:
        if args.reserve:
            reserve(args.directory, args.day, args.owner)
        elif not check(args.directory, args.day, args.owner):
            raise ValueError('lease_unavailable')
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({'ready': False, 'reason': 'lease_unavailable'}))
        return 1
    print(json.dumps({'ready': True, 'day': args.day, 'owner': args.owner}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
