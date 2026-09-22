"""Offline, bounded diagnostics never create tasks or alter news admission."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from manus_source import diagnostics
from manus_source.client import ManusClient
from _tempdir import make_temp_dir


def page(events=(), *, more=False, cursor=None):
    value = {'ok': True, 'messages': list(events), 'has_more': more}
    if cursor is not None:
        value['next_cursor'] = cursor
    return value


def event(event_id, brief='Read source list'):
    return {'id': event_id, 'type': 'tool_used', 'tool_used': {
        'tool': 'terminal', 'brief': brief,
        'message': {'action': 'Executing command', 'param': 'DO_NOT_EXECUTE_THIS'}}}


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir('manus-diagnostics-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        private_root = patch.object(diagnostics, 'PRIVATE_ROOT', self.root)
        private_root.start()
        self.addCleanup(private_root.stop)
        self.out = self.root / 'private-traces'
        self.calls = []

    def client(self, pages=(), status='stopped', credits=41, error=None):
        remaining = iter(pages)

        def transport(method, path, payload):
            self.calls.append((method, path, payload))
            self.assertEqual(method, 'GET')
            self.assertIsNone(payload)
            parsed = urlsplit(path)
            self.assertIn(parsed.path, ('task.detail', 'task.listMessages'))
            if error:
                raise error
            if parsed.path == 'task.detail':
                return {'ok': True, 'task': {'status': status, 'credit_usage': credits}}
            query = parse_qs(parsed.query)
            self.assertEqual(query['verbose'], ['true'])
            self.assertEqual(query['order'], ['asc'])
            self.assertEqual(query['limit'], ['200'])
            return next(remaining)

        return ManusClient('unused-private-key', 'manus-1.6', 0, 1,
                           transport=transport, create_retries=0)

    def test_reads_stopped_task_verbose_pages_and_saves_raw_privately(self):
        tool = event('one')
        result = diagnostics.capture_task_diagnostics(self.client([
            page([{'id': 'user', 'type': 'user_message', 'user_message': {
                'content': 'PRIVATE USER CONTENT', 'attachments': [{'url': 'https://example.org/a?signature=PRIVATE'}]}}, tool], more=True, cursor='page 2'),
            page([tool, event('two', 'Open https://user:pass@example.org/path?signature=PRIVATE api_key=SECRET')]),
        ]), 'task/id/../1', self.out)
        self.assertEqual((result['status'], result['credits']), ('stopped', 41))
        self.assertTrue(result['creditsObservedWithStoppedStatus'])
        self.assertTrue(result['traceComplete'])
        self.assertEqual((result['pages'], result['messageCount'], result['toolCount']), (2, 3, 2))
        self.assertEqual(result['lastToolBrief'], 'Open https://example.org/path [redacted]')
        self.assertEqual(parse_qs(urlsplit(self.calls[-1][1]).query)['cursor'], ['page 2'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('DO_NOT_EXECUTE', json.dumps(result))
        stem = hashlib.sha256(b'task/id/../1').hexdigest()
        raw = json.loads((self.out / f'{stem}.messages-001.json').read_text(encoding='utf-8'))
        self.assertEqual(raw['messages'][0]['user_message']['content'], 'PRIVATE USER CONTENT')
        self.assertEqual(len(list(self.out.iterdir())), 4)
        self.assertTrue(all(p.name.startswith(stem) for p in self.out.iterdir()))

    def test_nonstopped_tasks_only_read_detail(self):
        for status in ('running', 'waiting', 'error', 'unrecognized private status'):
            with self.subTest(status=status):
                self.calls.clear()
                result = diagnostics.capture_task_diagnostics(self.client(status=status), 'one', self.out)
                self.assertTrue(result['skipped'])
                self.assertFalse(result['traceComplete'])
                self.assertFalse(result['creditsObservedWithStoppedStatus'])
                self.assertEqual(result['pages'], 0)
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn('private status', json.dumps(result))

    def test_repeated_cursor_missing_cursor_and_page_limit_are_incomplete(self):
        cases = [([page(more=True, cursor='same'), page(more=True, cursor='same')], 5, 'repeated_cursor', 2),
                 ([page(more=True)], 5, 'missing_cursor', 1),
                 ([page(more=True, cursor='next')], 1, 'page_limit', 1),
                 ([page(more=False, cursor='next')], 5, 'invalid_pagination', 1)]
        for pages, limit, reason, count in cases:
            with self.subTest(reason=reason):
                self.calls.clear()
                result = diagnostics.capture_task_diagnostics(self.client(pages), reason, self.out, max_pages=limit)
                self.assertFalse(result['traceComplete'])
                self.assertEqual(result['incompleteReason'], reason)
                self.assertEqual(result['pages'], count)
                self.assertEqual(len(self.calls), count + 1)

    def test_page_bound_cannot_exceed_five(self):
        result = diagnostics.capture_task_diagnostics(
            self.client([page(more=True, cursor=str(i)) for i in range(5)]),
            'task', self.out, max_pages=100)
        self.assertEqual(result['pages'], 5)
        self.assertEqual(result['incompleteReason'], 'page_limit')
        self.assertEqual(len(self.calls), 6)

    def test_network_error_is_type_only_and_saved_without_retry(self):
        with self.assertLogs(diagnostics._LOG, 'WARNING') as logs:
            result = diagnostics.capture_task_diagnostics(
                self.client(error=RuntimeError('key=VERY_SECRET signed=https://host/?token=secret')),
                'task', self.out)
        self.assertEqual(result['errorType'], 'RuntimeError')
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('VERY_SECRET', json.dumps(result) + str(logs.output))
        self.assertTrue(list(self.out.glob('*.summary.json')))

    def test_write_failure_is_isolated_and_does_not_expand_requests(self):
        with patch.object(diagnostics, '_atomic_json', side_effect=OSError('PRIVATE STORAGE ERROR')):
            with self.assertLogs(diagnostics._LOG, 'WARNING') as logs:
                result = diagnostics.capture_task_diagnostics(self.client(), 'task', self.out)
        self.assertEqual(result['errorType'], 'OSError')
        self.assertFalse(result['traceComplete'])
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('PRIVATE STORAGE', str(result) + str(logs.output))

    def test_public_path_rejected_before_any_network(self):
        with self.assertLogs(diagnostics._LOG, 'WARNING'):
            result = diagnostics.capture_task_diagnostics(self.client(), 'task', self.root.parent / 'public')
        self.assertEqual(result['errorType'], 'ValueError')
        self.assertEqual(self.calls, [])

    def test_page_network_failure_preserves_completed_page_and_report(self):
        c = self.client([page([event('one')], more=True, cursor='two')])
        with self.assertLogs(diagnostics._LOG, 'WARNING'):
            result = diagnostics.capture_task_diagnostics(c, 'task', self.out)
        self.assertEqual(result['errorType'], 'StopIteration')
        self.assertEqual(result['pages'], 1)
        self.assertFalse(result['traceComplete'])
        self.assertEqual(len(list(self.out.glob('*.messages-*.json'))), 1)

    def test_malformed_tool_event_is_reported_without_propagating(self):
        with self.assertLogs(diagnostics._LOG, 'WARNING'):
            result = diagnostics.capture_task_diagnostics(self.client([
                page([{'type': 'tool_used', 'tool_used': 'invalid'}])]), 'task', self.out)
        self.assertEqual(result['errorType'], 'ValueError')
        self.assertFalse(result['traceComplete'])

    def test_request_payload_exact_private_record_and_hash_filename(self):
        payload = {'agent_profile': 'manus-1.6', 'message': {'content': 'PRIVATE PROMPT'}}
        result = diagnostics.record_task_request(self.out, payload, task_id='../task')
        self.assertTrue(result['saved'])
        self.assertEqual(result['filename'], hashlib.sha256(b'../task').hexdigest() + '.request.json')
        self.assertEqual(json.loads((self.out / result['filename']).read_text(encoding='utf-8')), payload)
        self.assertNotIn('PRIVATE PROMPT', json.dumps(result))
        before_create = diagnostics.record_task_request(self.out, payload)
        self.assertTrue(before_create['saved'])
        self.assertEqual(before_create['filename'], before_create['sha256'] + '.request.json')

    def test_request_headers_keys_and_filesystem_failures_are_isolated(self):
        for payload in ({'headers': {'x-manus-api-key': 'SECRET'}}, {'message': {'api_key': 'SECRET'}}):
            with self.subTest(payload=payload), self.assertLogs(diagnostics._LOG, 'WARNING'):
                result = diagnostics.record_task_request(self.out, payload)
            self.assertFalse(result['saved'])
            self.assertEqual(result['errorType'], 'ValueError')
            self.assertNotIn('SECRET', str(result))
        with patch.object(diagnostics, '_atomic_json', side_effect=PermissionError('secret')):
            with self.assertLogs(diagnostics._LOG, 'WARNING'):
                result = diagnostics.record_task_request(self.out, {'message': {'content': 'test'}})
        self.assertFalse(result['saved'])
        self.assertEqual(result['errorType'], 'PermissionError')


if __name__ == '__main__':
    unittest.main()
