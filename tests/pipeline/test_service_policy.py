"""Paused optional services fail before HTTP; direct collection remains usable."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from automation.runner import DIRECT_STAGES, normalize_source_mode, plan
from funding.search import tavily_search
from manus_source.client import ManusAPIError, default_transport
import service_policy
from testing.manus_probe import ProbeError, request


class ServicePolicyTests(unittest.TestCase):
    def test_checked_in_policy_pauses_both_services(self):
        self.assertFalse(service_policy.enabled('manus'))
        self.assertFalse(service_policy.enabled('tavily'))
        with self.assertRaisesRegex(ValueError, 'Unknown optional service'):
            service_policy.enabled('unknown')

    def test_manus_get_create_and_stop_never_reach_http_when_paused(self):
        with patch('manus_source.client.urlopen', side_effect=AssertionError('HTTP forbidden')) as http:
            for method, endpoint, payload in (
                ('POST', 'task.create', {'prompt': 'offline test'}),
                ('POST', 'task.stop', {'task_id': 'existing'}),
                ('GET', 'task.detail?task_id=existing', None),
                ('GET', 'task.listMessages?task_id=existing', None),
                ('GET', 'user.getBalance', None),
            ):
                with self.subTest(endpoint=endpoint), self.assertRaises(ManusAPIError) as caught:
                    default_transport(method, endpoint, payload, 'not-a-real-key')
                self.assertEqual(caught.exception.reason_code, 'service_paused')
                self.assertEqual(caught.exception.creation_state, 'not_created')
        http.assert_not_called()

    def test_probe_get_and_post_never_construct_http_opener_when_paused(self):
        with patch('testing.manus_probe.build_opener', side_effect=AssertionError('HTTP forbidden')) as opener:
            for method, endpoint in (('GET', 'user.getBalance'), ('POST', 'task.create')):
                with self.subTest(method=method), self.assertRaises(ProbeError) as caught:
                    request('not-a-real-key', method, endpoint, {} if method == 'POST' else None)
                self.assertEqual(caught.exception.code, 'service_paused')
        opener.assert_not_called()

    def test_tavily_never_reaches_http_when_paused(self):
        with patch('funding.search.urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')) as http:
            with self.assertRaisesRegex(ValueError, 'tavily service is paused'):
                tavily_search('offline company', 'not-a-real-key', 1)
        http.assert_not_called()

    def test_missing_or_malformed_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / 'services.json'
            with patch.object(service_policy, 'POLICY_PATH', policy):
                for raw in (None, '{broken', '[]', 'null', '{}',
                            json.dumps({'schemaVersion': 2, 'manus': True, 'tavily': True}),
                            json.dumps({'schemaVersion': 1, 'manus': 'true', 'tavily': 1})):
                    with self.subTest(raw=raw):
                        if raw is not None:
                            policy.write_text(raw, encoding='utf-8')
                        for name in ('manus', 'tavily'):
                            self.assertFalse(service_policy.enabled(name))
                            with self.assertRaisesRegex(ValueError, 'service is paused'):
                                service_policy.require(name)
                policy.unlink()
                with patch('manus_source.client.urlopen') as http, self.assertRaises(ManusAPIError):
                    default_transport('POST', 'task.create', {}, 'not-a-real-key')
                http.assert_not_called()

    def test_direct_default_and_full_alias_omit_paid_legacy_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for mode in (None, 'full', 'direct-only'):
                with self.subTest(mode=mode):
                    kwargs = {} if mode is None else {'source_mode': mode}
                    commands = plan(ROOT, workspace, '2026-09-23', ten_am=True, combined=True, **kwargs)
                    active = '\n'.join(' '.join(commands[stage]).replace('\\', '/') for stage in DIRECT_STAGES)
                    self.assertIn('collect_direct_news.py', active)
                    self.assertNotIn('manus_source/runner.py', active)
                    self.assertNotIn('--discover-company', active)
                    self.assertIn('--research-full-review', commands['overview'])
                    self.assertIn('--skip-search', commands['funding'])
            self.assertEqual(normalize_source_mode('full'), 'direct-only')


if __name__ == '__main__':
    unittest.main()
