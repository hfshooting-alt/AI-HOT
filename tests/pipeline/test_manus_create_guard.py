"""Unknown production creation outcomes must not permit more paid tasks."""
import unittest
from unittest.mock import patch

from manus_source.client import ManusAPIError, ManusClient


class ManusCreateGuardTests(unittest.TestCase):
    def client(self, transport, **kwargs):
        return ManusClient('offline', 'manus-1.6', 0, 1, transport=transport,
                           create_retries=0, require_terminal_confirmation=True, **kwargs)

    def create(self, client):
        return client.create_crawl_task('prompt', 'group_a', '2026-09-22', 'title', 'brief')

    def assert_blocked_after(self, outcome):
        calls, receipts = [], []

        def transport(method, path, payload):
            calls.append((method, path))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        client = self.client(transport)
        block = client.block_new_tasks
        locked = []

        def record_block():
            locked.append(client._create_lock.locked())
            block()

        with client.receipt_scope(receipts.append), patch.object(client, 'block_new_tasks', record_block):
            with self.assertRaises(Exception):
                self.create(client)
            first = receipts[-1]
            self.assertEqual(first['creationState'], 'unknown')
            self.assertEqual(first['createAttempts'], 1)
            self.assertIsNone(first['taskId'])
            with self.assertRaisesRegex(ManusAPIError, 'task not created'):
                self.create(client)
        self.assertEqual(calls, [('POST', 'task.create')])
        self.assertEqual(locked, [True], 'Circuit must close before another worker gets the create lock')
        self.assertEqual(receipts[-1]['creationState'], 'not_created')
        self.assertEqual(receipts[-1]['createAttempts'], 0)

    def test_transport_exceptions_close_circuit_without_retry(self):
        for error in (TimeoutError(), OSError(), ValueError(),
                      ManusAPIError('Manus HTTP 503'), ManusAPIError('Manus HTTP 429')):
            with self.subTest(error=type(error).__name__, message=str(error)):
                self.assert_blocked_after(error)

    def test_missing_or_unusable_task_id_closes_circuit(self):
        for response in ({'ok': True}, *({'ok': True, 'task_id': value}
                                       for value in (None, '', '  ', 42, [])), None):
            with self.subTest(response=response):
                self.assert_blocked_after(response)

    def test_explicit_rejection_conservatively_closes_circuit(self):
        self.assert_blocked_after({'ok': False, 'error': {'code': 'rejected', 'message': 'denied'}})

    def test_known_task_id_survives_missing_or_invalid_url(self):
        for url in (None, '', ' ', 3):
            with self.subTest(url=url):
                receipts, calls = [], []

                def transport(method, path, payload):
                    calls.append((method, path))
                    response = {'ok': True, 'task_id': 'real-task'}
                    if url is not None:
                        response['task_url'] = url
                    return response

                client = self.client(transport)
                with client.receipt_scope(receipts.append):
                    task = self.create(client)
                self.assertEqual(task.task_id, 'real-task')
                self.assertEqual(task.task_url, 'https://manus.im/app/real-task')
                self.assertEqual(receipts[-1]['taskId'], 'real-task')
                self.assertEqual(receipts[-1]['creationState'], 'created')
                self.assertFalse(client._creation_blocked.is_set())
                self.assertEqual(calls, [('POST', 'task.create')])

    def test_default_legacy_retry_still_works(self):
        outcomes = [ManusAPIError('Manus HTTP 503'),
                    {'ok': True, 'task_id': 'legacy-task', 'task_url': 'https://example.com/task'}]
        calls = []

        def transport(method, path, payload):
            calls.append((method, path))
            response = outcomes.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        client = ManusClient('offline', 'manus-1.6', 0, 1, transport=transport,
                             retry_base_seconds=0, retry_jitter_seconds=0)
        self.assertEqual(self.create(client).task_id, 'legacy-task')
        self.assertEqual(len(calls), 2)
        self.assertFalse(client._creation_blocked.is_set())
