"""Profile balances and bounded production credit visibility; no live requests."""
import unittest
from unittest.mock import patch

from manus_source.client import CreatedTask, ManusAPIError, ManusClient
from manus_source.runner import DiscoveryRunError, run_discovery


class Clock:
    def __init__(self):
        self.value = 0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class ManusCreditGuardTests(unittest.TestCase):
    def client(self, transport, profile='manus-1.6', production=True, **kwargs):
        return ManusClient('offline', profile, 30, 600, transport=transport,
                           require_terminal_confirmation=production, create_retries=0, **kwargs)

    def test_profile_usable_balance_for_both_response_shapes(self):
        for nested in (False, True):
            for profile, expected in (('manus-1.6', 212), ('manus-1.6-max', 212), ('manus-1.6-lite', 506)):
                with self.subTest(nested=nested, profile=profile):
                    balance = {'total_credits': 506, 'refresh_credits': 294}
                    response = {'ok': True, 'data': balance} if nested else {'ok': True, **balance}
                    client = self.client(lambda *args: response, profile=profile)
                    self.assertEqual(client.available_credits(), expected)
                    self.assertEqual(client.last_credit_balance, {'total': 506, 'refresh': 294,
                        'usable': expected, 'profile': profile, 'complete': True})

    def test_daily_only_balance_is_zero_for_standard(self):
        client = self.client(lambda *args: {'ok': True, 'total_credits': 294, 'refresh_credits': 294})
        self.assertEqual(client.available_credits(), 0)

    def test_missing_refresh_fails_closed_in_production_and_marks_legacy(self):
        for profile in ('manus-1.6', 'manus-1.6-lite'):
            client = self.client(lambda *args: {'ok': True, 'total_credits': 506}, profile)
            with self.assertRaisesRegex(ManusAPIError, 'refresh credits missing'):
                client.available_credits()
            self.assertIsNone(client.last_credit_balance['usable'])
            self.assertFalse(client.last_credit_balance['complete'])
        legacy = self.client(lambda *args: {'ok': True, 'data': {'total_credits': 506}}, production=False)
        self.assertEqual(legacy.available_credits(), 506)
        self.assertEqual(legacy.last_credit_balance['usable'], 506)
        self.assertFalse(legacy.last_credit_balance['complete'])

    def test_invalid_refresh_never_becomes_spendable(self):
        for value in (None, True, '294', 294.0, -1, 507):
            for production in (True, False):
                with self.subTest(value=value, production=production):
                    client = self.client(lambda *args: {'ok': True, 'total_credits': 506,
                                         'refresh_credits': value}, production=production)
                    with self.assertRaisesRegex(ManusAPIError, 'invalid refresh'):
                        client.available_credits()
                    self.assertIsNone(client.last_credit_balance['usable'])
                    self.assertFalse(client.last_credit_balance['complete'])

    def test_failed_balance_refresh_clears_previous_usable_observation(self):
        responses = iter([{'ok': True, 'total_credits': 506, 'refresh_credits': 294},
                          {'ok': True, 'total_credits': True, 'refresh_credits': 0}])
        client = self.client(lambda *args: next(responses))
        self.assertEqual(client.available_credits(), 212)
        with self.assertRaises(ManusAPIError):
            client.available_credits()
        self.assertIsNone(client.last_credit_balance['usable'])
        self.assertIsNone(client.last_credit_balance['total'])

    def test_insufficient_credit_errors_block_new_creations(self):
        outcomes = [ManusAPIError('Manus HTTP 503: not enough credits'),
                    {'ok': True, 'messages': [{'type': 'error_message',
                     'error_message': {'content': 'NOT_ENOUGH_CREDITS'}}]}]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                calls = []
                def transport(method, path, payload):
                    calls.append((method, path))
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome
                client = self.client(transport)
                with self.assertRaises(ManusAPIError):
                    client.wait_for_structured_result('known', observed_credit_limit=12)
                self.assertTrue(client._creation_blocked.is_set())
                with self.assertRaisesRegex(ManusAPIError, 'task not created'):
                    client.create_crawl_task('p', 'g', 'd', 't', 'b')
                self.assertEqual(len(calls), 1)

    def test_credit_error_after_result_still_blocks_next_source(self):
        final = {'articles': []}
        response = {'ok': True, 'messages': [
            {'type': 'structured_output_result', 'structured_output_result': {'success': True, 'value': final}},
            {'type': 'error_message', 'error_message': {'content': 'not enough credits'}}]}
        client = self.client(lambda *args: response)
        self.assertEqual(client.wait_for_structured_result('known', observed_credit_limit=12), final)
        self.assertTrue(client._creation_blocked.is_set())

    def fee_transport(self, clock, values):
        reads = []
        def transport(method, path, payload):
            if path.startswith('task.listMessages?'):
                return {'ok': True, 'messages': []}
            if path.startswith('task.detail?'):
                reads.append(clock.value)
                value = values(clock.value)
                return {'ok': True, 'task': {'status': 'running', 'credit_usage': value}}
            raise AssertionError('Unexpected operation')
        return transport, reads

    def test_invalid_fee_observations_stop_at_90_seconds(self):
        for invalid in (None, '0', True, -1, float('nan'), float('inf')):
            with self.subTest(invalid=invalid):
                clock = Clock()
                transport, reads = self.fee_transport(clock, lambda _: invalid)
                client = self.client(transport)
                with patch('manus_source.client.time.monotonic', clock.now), patch('manus_source.client.time.sleep', clock.sleep):
                    with self.assertRaisesRegex(ManusAPIError, 'credit usage unavailable'):
                        client.wait_for_structured_result('known', observed_credit_limit=12)
                self.assertEqual(clock.value, 90)
                self.assertEqual(reads, [0, 30, 60, 90])

    def test_valid_zero_fee_resets_missing_observation_grace(self):
        clock = Clock()
        transport, reads = self.fee_transport(clock, lambda t: 0 if t == 60 else None)
        client = self.client(transport)
        with patch('manus_source.client.time.monotonic', clock.now), patch('manus_source.client.time.sleep', clock.sleep):
            with self.assertRaisesRegex(ManusAPIError, 'credit usage unavailable'):
                client.wait_for_structured_result('known', observed_credit_limit=12)
        self.assertEqual(clock.value, 150)
        self.assertEqual(reads[-1], 150)

    def test_retryable_read_failures_cannot_extend_missing_fee_grace(self):
        clock = Clock()
        def transport(*args):
            raise ManusAPIError('Manus HTTP 503')
        client = self.client(transport)
        with patch('manus_source.client.time.monotonic', clock.now), patch('manus_source.client.time.sleep', clock.sleep):
            with self.assertRaisesRegex(ManusAPIError, 'credit usage unavailable'):
                client.wait_for_structured_result('known', observed_credit_limit=12)
        self.assertEqual(clock.value, 90)

    def test_legacy_missing_fee_keeps_existing_timeout_behavior(self):
        clock = Clock()
        transport, _ = self.fee_transport(clock, lambda _: None)
        client = self.client(transport, production=False)
        client.timeout_seconds = 120
        with patch('manus_source.client.time.monotonic', clock.now), patch('manus_source.client.time.sleep', clock.sleep):
            with self.assertRaises(TimeoutError):
                client.wait_for_structured_result('known', observed_credit_limit=12)
        self.assertEqual(clock.value, 120)

    def test_missing_fee_uses_existing_stop_and_confirmation_path(self):
        clock = Clock()
        transport, _ = self.fee_transport(clock, lambda _: None)
        client = self.client(transport)
        with patch('manus_source.client.time.monotonic', clock.now), patch('manus_source.client.time.sleep', clock.sleep), \
             patch.object(client, 'create_crawl_task', return_value=CreatedTask('known', 'https://example.com/task')), \
             patch.object(client, 'stop_task') as stop, patch.object(client, 'read_stopped_results', return_value=None), \
             patch.object(client, 'confirm_task_stopped', return_value={'confirmed': True, 'remoteStatus': 'stopped'}) as confirm:
            with self.assertRaises(DiscoveryRunError) as caught:
                run_discovery(client, 'group_a', '2026-09-22', 'prompt', ['Example'], observed_credit_limit=12)
        self.assertTrue(caught.exception.stop_succeeded)
        stop.assert_called_once_with('known')
        confirm.assert_called_once_with('known')
