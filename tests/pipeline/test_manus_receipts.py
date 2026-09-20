"""Task receipts distinguish observed execution from configured/cached sources, offline."""
import contextlib
import base64
import io
import json
import re
import shutil
import sys
import unittest
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from manus_source import runner
from manus_source.client import ManusAPIError, ManusClient
from _tempdir import make_temp_dir


def client(transport):
    return ManusClient('private-key', 'manus-1.6', 0, 2, transport=transport, create_retries=0)


def terminal_page(name='Source'):
    return {'ok': True, 'messages': [
        {'type': 'status_update', 'timestamp': '1789886400000',
         'status_update': {'agent_status': 'running'}},
        {'type': 'structured_output_result', 'structured_output_result': {
            'success': True, 'value': {'source_group': 'group_a', 'target_date': '2026-09-20',
                'source_audits': [{'account_name': name, 'source_status': 'complete',
                                   'article_count': 0, 'note': 'No matching articles'}], 'articles': []}}},
        {'type': 'status_update', 'timestamp': '1789886430000',
         'status_update': {'agent_status': 'stopped'}}]}


class ReceiptClientTests(unittest.TestCase):
    def test_zero_article_success_records_terminal_after_result_without_extra_reads(self):
        calls, receipts = [], []

        def transport(method, path, payload):
            calls.append((method, path))
            if path == 'task.create':
                return {'ok': True, 'task_id': 'task-1', 'task_url': 'https://example.com/task-1'}
            self.assertTrue(path.startswith('task.listMessages?'))
            return terminal_page()

        c = client(transport)
        with c.receipt_scope(receipts.append):
            task = c.create_crawl_task('PRIVATE PROMPT', 'group_a', '2026-09-20', 'title', 'brief')
            result = c.wait_for_structured_result(task.task_id, observed_credit_limit=20)
        self.assertEqual(result['articles'], [])
        receipt = receipts[-1]
        self.assertEqual(receipt['taskId'], 'task-1')
        self.assertEqual(receipt['createAttempts'], 1)
        self.assertEqual(receipt['lastRemoteStatus'], 'stopped')
        self.assertTrue(receipt['terminalConfirmed'])
        self.assertEqual(receipt['terminalEventAt'], '2026-09-20T14:40:30.000+08:00')
        self.assertNotEqual(receipt['terminalObservedAt'], receipt['terminalEventAt'])
        self.assertLessEqual(receipt['createRequestedObservedAt'], receipt['createdResponseObservedAt'])
        self.assertNotIn('remoteCreatedAt', receipt)
        self.assertEqual(len(calls), 2)
        self.assertEqual(c.confirm_task_stopped('task-1')['confirmed'], True)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('PRIVATE PROMPT', json.dumps(receipts))
        self.assertNotIn('private-key', json.dumps(receipts))

    def test_stop_accepted_running_is_unknown_terminal_and_remote_times_remain_separate(self):
        calls = []

        def transport(method, path, payload):
            calls.append((method, path))
            if path == 'task.stop':
                return {'ok': True}
            return {'ok': True, 'task': {'status': 'running', 'created_at': '1789886400',
                                       'updated_at': '1789886430', 'credit_usage': 21}}

        c = client(transport)
        c.stop_task('task-1')
        with patch('manus_source.client.time.sleep'):
            result = c.confirm_task_stopped('task-1')
        receipt = c.task_receipt('task-1')
        self.assertTrue(receipt['stopAccepted'])
        self.assertFalse(result['confirmed'])
        self.assertFalse(receipt['terminalConfirmed'])
        self.assertIsNone(receipt.get('terminalObservedAt'))
        self.assertEqual(receipt['remoteCreatedAt'], '2026-09-20T14:40:00.000+08:00')
        self.assertEqual(receipt['lastObservedCredits'], 21)
        self.assertFalse(receipt['creditsObservedWithTerminalStatus'])
        self.assertEqual(len(calls), 4)  # Existing bounded confirmation only.

    def test_creation_blocked_and_uncertain_are_not_successful_creations(self):
        calls, receipts = [], []

        def transport(method, path, payload):
            calls.append(path)
            raise ManusAPIError('Cannot reach Manus API: connection reset')

        c = client(transport)
        c.block_new_tasks()
        with c.receipt_scope(receipts.append), self.assertRaises(ManusAPIError):
            c.create_crawl_task('p', 'g', 'd', 't', 'b')
        self.assertEqual(receipts[-1]['creationState'], 'not_created')
        self.assertEqual(receipts[-1]['createAttempts'], 0)
        self.assertEqual(calls, [])
        c = client(transport)
        with c.receipt_scope(receipts.append), self.assertRaises(ManusAPIError):
            c.create_crawl_task('p', 'g', 'd', 't', 'b')
        self.assertEqual(receipts[-1]['creationState'], 'unknown')
        self.assertEqual(receipts[-1]['createAttempts'], 1)
        self.assertIsNone(receipts[-1]['taskId'])
        self.assertEqual(calls, ['task.create'])

    def test_callback_runtime_error_cannot_orphan_created_task_or_retry(self):
        calls = []

        def transport(method, path, payload):
            calls.append(path)
            if path == 'task.create':
                return {'ok': True, 'task_id': 'task-1', 'task_url': 'https://example.com/task-1'}
            if path == 'task.stop':
                return {'ok': True}
            return terminal_page()

        def broken(_receipt):
            raise RuntimeError('private diagnostic details must not be printed')

        c = client(transport)
        output = io.StringIO()
        with c.receipt_scope(broken), contextlib.redirect_stdout(output):
            task = c.create_crawl_task('p', 'g', 'd', 't', 'b')
            c.stop_task(task.task_id)
            c.read_stopped_results(task.task_id, lambda article: None)
            self.assertTrue(c.confirm_task_stopped(task.task_id)['confirmed'])
        self.assertEqual(calls.count('task.create'), 1)
        self.assertEqual(calls.count('task.stop'), 1)
        self.assertEqual(len(calls), 3)
        self.assertIn('RuntimeError', output.getvalue())
        self.assertNotIn('private diagnostic details', output.getvalue())


class ReceiptRunnerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir('manus-receipts-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.sources = self.root / 'sources.json'
        self.sources.write_text(json.dumps({'groups': {'group_a': [{'account_name': 'Source',
            'platform': 'Tencent News', 'home_url': 'https://example.com/source'}]}}), encoding='utf-8')
        self.prompt = self.root / 'prompt.md'
        self.prompt.write_text('{{SOURCES}}', encoding='utf-8')
        self.settings = runner.Settings(
            manus_api_key='fake', manus_agent_profile='manus-1.6', poll_seconds=0,
            timeout_seconds=2, register_grace_seconds=0, content_batch_size=4,
            content_concurrency=2, content_mode='script', crawl_timeout_seconds=20,
            crawl_retries=0, crawl_concurrency=1, crawl_request_delay_seconds=0,
            crawl_user_agent=None, crawl_jina_fallback=False, max_content_chars=20000,
            min_content_chars=100, sources_path=self.sources, discovery_prompt_path=self.prompt,
            content_prompt_path=self.prompt, work_dir=self.root / 'work')

    def test_success_zero_cache_and_budget_block_have_distinct_receipts(self):
        calls = []

        def transport(method, path, payload):
            calls.append(path)
            if path == 'usage.availableCredits':
                return {'ok': True, 'total_credits': 100}
            if path == 'task.create':
                return {'ok': True, 'task_id': 'task-1', 'task_url': 'https://example.com/task-1'}
            return terminal_page()

        class FakeClient(ManusClient):
            def __init__(self, **kwargs):
                kwargs['transport'] = transport
                kwargs['create_interval_seconds'] = 0
                super().__init__(**kwargs)

        args = ['--date', '2026-09-20', '--groups', 'group_a', '--credit-limit-per-source', '20']
        with patch.object(runner.Settings, 'from_environment', return_value=self.settings), \
             patch.object(runner, 'ManusClient', FakeClient):
            self.assertEqual(runner.main(args), 0)
            path = self.settings.work_dir / '2026-09-20/cost-report.json'
            first = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(first['createdSourceCount'], 1)
            self.assertEqual(first['observedTerminalTaskCount'], 1)
            self.assertEqual(first['sourceReceipts'][0]['articleCount'], 0)
            self.assertEqual(first['sourceReceipts'][0]['taskId'], 'task-1')
            self.assertEqual(runner.main(args), 0)
            cached = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(cached['cachedSourceCount'], 1)
            self.assertEqual(cached['createdSourceCount'], 0)
            self.assertEqual(cached['attemptedSourceCount'], 0)
            self.assertIsNone(cached['sourceReceipts'][0]['taskId'])
            self.assertEqual(calls.count('task.create'), 1)
            self.assertTrue(list((path.parent / 'cost-history').glob('*.json')))

        class NoBudget(FakeClient):
            def available_credits(self):
                return 0

        with patch.object(runner.Settings, 'from_environment', return_value=self.settings), \
             patch.object(runner, 'ManusClient', NoBudget):
            self.assertEqual(runner.main(args), 1)
        blocked = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(blocked['notCreatedSourceCount'], 1)
        self.assertEqual(blocked['sourceReceipts'][0]['notCreatedReason'], 'budget_unavailable')
        self.assertEqual(calls.count('task.create'), 1)

    def test_atomic_receipt_write_failure_does_not_change_successful_collection(self):
        calls = []

        def transport(method, path, payload):
            calls.append(path)
            if path == 'usage.availableCredits':
                return {'ok': True, 'total_credits': 100}
            if path == 'task.create':
                return {'ok': True, 'task_id': 'task-1', 'task_url': 'https://example.com/task-1'}
            return terminal_page()

        class FakeClient(ManusClient):
            def __init__(self, **kwargs):
                kwargs.update(transport=transport, create_interval_seconds=0)
                super().__init__(**kwargs)

        original_replace = Path.replace

        def fail_receipt(path, target):
            if path.name == 'cost-report.tmp':
                raise OSError('simulated receipt filesystem failure')
            return original_replace(path, target)

        with patch.object(runner.Settings, 'from_environment', return_value=self.settings), \
             patch.object(runner, 'ManusClient', FakeClient), patch.object(Path, 'replace', fail_receipt):
            result = runner.main(['--date', '2026-09-20', '--groups', 'group_a',
                                  '--credit-limit-per-source', '20'])
        self.assertEqual(result, 0)
        report = json.loads((self.settings.work_dir / '2026-09-20/cost-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['receiptWriteError'], 'OSError')
        self.assertEqual(report['createdSourceCount'], 1)
        self.assertEqual(report['observedTerminalTaskCount'], 1)
        self.assertEqual(calls.count('task.create'), 1)
        self.assertEqual(len(calls), 4)

    def test_twenty_sources_keep_distinct_receipts_with_three_concurrent_workers(self):
        sources = [{'account_name': f'Source{i}', 'platform': 'Tencent News',
                    'home_url': f'https://example.com/Source{i}'} for i in range(20)]
        self.sources.write_text(json.dumps({'groups': {'group_a': sources}}), encoding='utf-8')
        lock, first_three = Lock(), Barrier(3)
        active = peak = created = 0

        def transport(method, path, payload):
            nonlocal active, peak, created
            if path == 'usage.availableCredits':
                return {'ok': True, 'total_credits': 1000}
            if path == 'task.create':
                attachment = payload['message']['content'][1]['file_data']
                prompt = base64.b64decode(attachment.split(',', 1)[1]).decode()
                name = re.search(r'https://example.com/(Source\d+)', prompt)[1]
                with lock:
                    active += 1
                    peak = max(peak, active)
                    created += 1
                return {'ok': True, 'task_id': name, 'task_url': f'https://example.com/task/{name}'}
            name = re.search(r'task_id=(Source\d+)', path)[1]
            if name in ('Source0', 'Source1', 'Source2'):
                first_three.wait(timeout=5)
            with lock:
                active -= 1
            return terminal_page(name)

        class FakeClient(ManusClient):
            def __init__(self, **kwargs):
                kwargs.update(transport=transport, create_interval_seconds=0)
                super().__init__(**kwargs)

        with patch.object(runner.Settings, 'from_environment', return_value=self.settings), \
             patch.object(runner, 'ManusClient', FakeClient):
            result = runner.main(['--date', '2026-09-20', '--groups', 'group_a',
                                  '--credit-limit-per-source', '20'])
        self.assertEqual(result, 0)
        self.assertEqual((created, peak, active), (20, 3, 0))
        report = json.loads((self.settings.work_dir / '2026-09-20/cost-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['createdSourceCount'], 20)
        self.assertEqual(report['observedTerminalTaskCount'], 20)
        self.assertEqual(report['creationUnknownSourceCount'], 0)
        self.assertEqual({r['accountName'] for r in report['sourceReceipts']},
                         {s['account_name'] for s in sources})
        for receipt in report['sourceReceipts']:
            self.assertEqual(receipt['accountName'], receipt['taskId'])
            self.assertEqual(receipt['createAttempts'], 1)
            self.assertTrue(receipt['terminalObservedAt'])


if __name__ == '__main__':
    unittest.main()
