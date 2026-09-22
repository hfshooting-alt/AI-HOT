"""Private, best-effort evidence capture; never part of article admission.

Only documented GET task.detail and task.listMessages are used. A credit reading
is an observation, not a service-side spending cap or proof of final settlement.
Stop acceptance is not termination: verbose history is read only after detail
reports stopped. Tool descriptions/parameters are data and are never executed.
Raw requests/responses must stay below the repository's private work directory.
"""
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode, urlsplit, urlunsplit


PRIVATE_ROOT = Path(__file__).resolve().parents[2] / 'work'
_LOG = logging.getLogger(__name__)
_MAX_PAGES = 5


def _private_dir(output_dir):
    path = Path(output_dir).resolve()
    if not path.is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Private work directory required')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                prefix='.' + path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _error(summary, error):
    # No exception message/traceback: transport errors may contain credentials.
    kind = type(error).__name__
    summary.setdefault('errorTypes', []).append(kind)
    summary['errorType'] = kind
    try:
        _LOG.warning('Manus diagnostics unavailable (%s)', kind)
    except Exception:
        pass  # A logging handler must not change the task's lifecycle either.


def _safe_brief(value):
    if not isinstance(value, str):
        return None

    def redact_url(match):
        try:
            parts = urlsplit(match.group())
            # Drop credentials, query strings and fragments, including signatures.
            return urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))
        except ValueError:
            return '[URL]'

    text = re.sub(r'https?://[^\s<>"`]+', redact_url, value)
    text = re.sub(r'(?i)\b(?:authorization|api[-_ ]?key|x-manus-api-key|token|secret)\s*[:=]\s*\S+',
                  '[redacted]', text)
    text = re.sub(r'(?i)\bbearer\s+\S+', '[redacted]', text)
    return ' '.join(text.split())[:160]


def _get(client, endpoint, query):
    if endpoint not in ('task.detail', 'task.listMessages'):
        raise ValueError('Unsupported diagnostic endpoint')
    result = client._request('GET', endpoint + '?' + urlencode(query))
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise ValueError('Invalid diagnostic response')
    return result


def capture_task_diagnostics(client, task_id, output_dir, max_pages=5):
    """Return a safe summary, with bounded raw evidence in private work storage.

    At most one detail GET and five verbose-page GETs; no retries, sleeps, task
    creation, continuation or stopping. Running/waiting/unknown tasks are skipped.
    Network, validation, logging and filesystem exceptions are isolated from the
    caller. ``traceComplete`` describes pagination, not successful news coverage.
    """
    summary = {'status': 'unknown', 'credits': None, 'toolCount': 0,
               'messageCount': 0, 'pages': 0, 'traceComplete': False,
               'lastToolBrief': None, 'skipped': False,
               'observedAt': datetime.now(timezone.utc).isoformat()}
    directory = stem = None
    try:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError('Task ID required')
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError('Positive page bound required')
        max_pages = min(max_pages, _MAX_PAGES)
        directory, stem = _private_dir(output_dir), _hash(task_id)
        detail = _get(client, 'task.detail', {'task_id': task_id})
        _atomic_json(directory / f'{stem}.detail.json', detail)
        task = detail.get('task')
        if not isinstance(task, dict):
            raise ValueError('Task details missing')
        status = task.get('status')
        summary['status'] = status if status in ('running', 'stopped', 'waiting', 'error') else 'unknown'
        credits = task.get('credit_usage')
        if type(credits) in (int, float) and math.isfinite(credits) and credits >= 0:
            summary['credits'] = credits
        summary['creditsObservedWithStoppedStatus'] = status == 'stopped' and summary['credits'] is not None
        if status != 'stopped':
            summary.update(skipped=True, incompleteReason='task_not_stopped')
        else:
            cursor, seen_cursors, seen_events = None, set(), set()
            for page in range(1, max_pages + 1):
                query = {'task_id': task_id, 'verbose': 'true', 'order': 'asc', 'limit': '200'}
                if cursor:
                    query['cursor'] = cursor
                response = _get(client, 'task.listMessages', query)
                summary['pages'] = page
                _atomic_json(directory / f'{stem}.messages-{page:03d}.json', response)
                events = response.get('messages')
                if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):
                    raise ValueError('Invalid event list')
                for index, event in enumerate(events):
                    event_id = event.get('id')
                    identity = event_id if isinstance(event_id, str) else (page, index)
                    if identity in seen_events:
                        continue
                    seen_events.add(identity)
                    summary['messageCount'] += 1
                    if event.get('type') == 'tool_used':
                        tool = event.get('tool_used')
                        if not isinstance(tool, dict):
                            raise ValueError('Invalid tool event')
                        summary['toolCount'] += 1
                        summary['lastToolBrief'] = _safe_brief(tool.get('brief'))
                cursor = response.get('next_cursor')
                has_more = response.get('has_more')
                if has_more is False and not cursor:
                    summary['traceComplete'] = True
                    break
                if has_more is not True or (cursor is not None and not isinstance(cursor, str)):
                    summary['incompleteReason'] = 'invalid_pagination'
                    break
                if not cursor:
                    summary['incompleteReason'] = 'missing_cursor'
                    break
                if cursor in seen_cursors:
                    summary['incompleteReason'] = 'repeated_cursor'
                    break
                seen_cursors.add(cursor)
            else:
                summary['incompleteReason'] = 'page_limit'
    except Exception as error:
        summary['traceComplete'] = False
        _error(summary, error)
    if directory is not None and stem is not None:
        try:
            _atomic_json(directory / f'{stem}.summary.json', summary)
        except Exception as error:
            _error(summary, error)
    return summary


def _has_credentials(value):
    if isinstance(value, dict):
        return any(str(key).lower().replace('-', '_') in
                   ('headers', 'authorization', 'api_key', 'manus_api_key', 'x_manus_api_key')
                   or _has_credentials(child) for key, child in value.items())
    return isinstance(value, list) and any(_has_credentials(child) for child in value)


def record_task_request(output_dir, payload, task_id=None):
    """Save the create payload only, never headers or a client/settings object.

    Returns a filename/hash on success or an exception type on failure; never
    raises and never sends any API request. No task ID is interpolated into paths.
    """
    report = {'saved': False}
    try:
        if not isinstance(payload, dict) or _has_credentials(payload):
            raise ValueError('Only a credential-free create payload is accepted')
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = _hash(encoded)
        if task_id is not None and not isinstance(task_id, str):
            raise ValueError('Invalid task ID')
        stem = _hash(task_id) if task_id is not None else digest
        directory = _private_dir(output_dir)
        filename = f'{stem}.request.json'
        _atomic_json(directory / filename, payload)
        report.update(saved=True, filename=filename, sha256=digest)
    except Exception as error:
        _error(report, error)
    return report
