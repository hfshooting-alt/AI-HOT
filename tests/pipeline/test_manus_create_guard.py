"""Unknown production creation outcomes must not permit more paid tasks."""
import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from manus_source.client import ManusAPIError, ManusClient, default_transport


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

        def record_block(*args):
            locked.append(client._create_lock.locked())
            block(*args)

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

    def test_observed_credit_rejection_marks_not_created_and_preserves_safe_reason(self):
        response = {'ok': False, 'error': {'code': 'resource_exhausted', 'message': 'credit limit exceeded'}}
        for via_http in (False, True):
            with self.subTest(via_http=via_http):
                receipts = []
                error = HTTPError('https://api.manus.ai/v2/task.create', 429, 'denied', {},
                                  io.BytesIO(json.dumps(response).encode()))
                transport = ((lambda *args: default_transport(*args, 'private-test-key')) if via_http
                             else lambda *args: response)
                client = self.client(transport)
                with patch('manus_source.client.urlopen', side_effect=error) as http, \
                     patch('service_policy.enabled', return_value=True), \
                     client.receipt_scope(receipts.append):
                    with self.assertRaisesRegex(ManusAPIError, 'account_credits_exhausted'):
                        self.create(client)
                    first = dict(receipts[-1])
                    with self.assertRaisesRegex(ManusAPIError, 'account_credits_exhausted') as queued:
                        self.create(client)
                self.assertEqual(first['creationState'], 'not_created')
                self.assertEqual(first['createAttempts'], 1)
                self.assertEqual(first['notCreatedReason'], 'account_credits_exhausted')
                self.assertEqual(receipts[-1]['createAttempts'], 0)
                self.assertEqual(receipts[-1]['notCreatedReason'], 'account_credits_exhausted')
                self.assertNotIn('remote stop', str(queued.exception))
                self.assertNotIn('private-test-key', json.dumps(receipts))
                self.assertEqual(http.call_count, int(via_http))
                client.block_new_tasks()  # Later cleanup must not replace the first cause.
                self.assertEqual(client.creation_blocked_error().reason_code, 'account_credits_exhausted')

    def test_http_5xx_or_ambiguous_credit_errors_remain_creation_unknown(self):
        for status, body in (
            (503, {'ok': False, 'error': {'code': 'resource_exhausted', 'message': 'credit limit exceeded'}}),
            (429, {'ok': False, 'error': {'code': 'resource_exhausted', 'message': 'rate limited'}}),
            (429, {'ok': False, 'task_id': 'possibly-created',
                   'error': {'code': 'resource_exhausted', 'message': 'credit limit exceeded'}}),
            (429, {'error': {'code': 'resource_exhausted', 'message': 'credit limit exceeded'}}),
        ):
            with self.subTest(status=status, body=body):
                receipts = []
                error = HTTPError('https://api.manus.ai/v2/task.create', status, 'failure', {},
                                  io.BytesIO(json.dumps(body).encode()))
                client = self.client(lambda *args: default_transport(*args, 'offline'))
                with patch('manus_source.client.urlopen', side_effect=error), \
                     patch('service_policy.enabled', return_value=True), client.receipt_scope(receipts.append):
                    with self.assertRaises(ManusAPIError):
                        self.create(client)
                self.assertEqual(receipts[-1]['creationState'], 'unknown')
                self.assertEqual(client.creation_blocked_error().reason_code, 'creation_unknown')

    def test_credit_rejection_does_not_block_existing_task_reads_or_stop(self):
        calls = []
        def transport(method, path, payload):
            calls.append(path)
            if path == 'task.create':
                return {'ok': False, 'error': {'code': 'resource_exhausted', 'message': 'credit limit exceeded'}}
            return {'ok': True, 'task': {'status': 'stopped'}}
        client = self.client(transport)
        with self.assertRaises(ManusAPIError):
            self.create(client)
        client.stop_task('existing-task')
        self.assertTrue(client.confirm_task_stopped('existing-task')['confirmed'])
        self.assertEqual(calls, ['task.create', 'task.stop', 'task.detail?task_id=existing-task'])

    def test_known_refusal_after_legacy_unknown_attempt_cannot_erase_uncertainty(self):
        responses = [ManusAPIError('Manus HTTP 503'),
                     {'ok': False, 'error': {'code': 'resource_exhausted', 'message': 'credit limit exceeded'}}]
        def transport(*args):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        client = ManusClient('offline', 'manus-1.6', 0, 1, transport=transport,
                             retry_base_seconds=0, retry_jitter_seconds=0)
        receipts = []
        with client.receipt_scope(receipts.append), self.assertRaises(ManusAPIError) as caught:
            self.create(client)
        self.assertEqual(receipts[-1]['creationState'], 'unknown')
        self.assertEqual(receipts[-1]['createAttempts'], 2)
        self.assertEqual(caught.exception.creation_state, 'unknown')
        self.assertEqual(responses, [])

    def test_legacy_retry_blocked_before_send_preserves_first_unknown_attempt(self):
        calls, receipts = [], []
        def transport(*args):
            calls.append(args)
            raise ManusAPIError('Manus HTTP 503')
        client = ManusClient('offline', 'manus-1.6', 0, 1, transport=transport,
                             retry_base_seconds=0, retry_jitter_seconds=0)
        with patch('manus_source.client.time.sleep', side_effect=lambda _: client.block_new_tasks()), \
             client.receipt_scope(receipts.append), self.assertRaises(ManusAPIError) as caught:
            self.create(client)
        self.assertEqual(len(calls), 1)
        self.assertEqual(receipts[-1]['creationState'], 'unknown')
        self.assertEqual(receipts[-1]['createAttempts'], 1)
        self.assertEqual(caught.exception.creation_state, 'unknown')
        self.assertNotIn('account_credits_exhausted', str(caught.exception))

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
