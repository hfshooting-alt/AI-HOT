"""Offline regression for safe failure logs, bounded queues and publication gates."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from llm_failures import FailureCircuit, LLMRequestError, safe_error
import llm_common
from company_index import extraction as companies
from funding import extraction as funding
import funding_table

TX = json.loads((ROOT / 'config/taxonomy.json').read_text(encoding='utf-8'))


def articles(count):
    return [{'id': str(i), 'title': 'Example', 'sourceName': 'Source', 'mpName': 'Source',
             'url': f'https://example.com/{i}', 'category': 'general',
             'content_text': 'Offline test content. ' * 8} for i in range(count)]


class FailureDiagnosticsTest(unittest.TestCase):
    def test_http_error_is_logged_once_without_secret_or_response(self):
        with tempfile.TemporaryDirectory() as temp:
            usage = Path(temp) / 'usage.jsonl'
            exc = urllib.error.HTTPError('https://example.com/private-key', 401,
                                        'secret-detail', {'Authorization': 'secret-header'},
                                        io.BytesIO(b'private-article-body'))
            model = TX['model']
            with patch.dict(os.environ, {model['api_key_env']: 'fake-key',
                                         model['api_base_env']: 'https://example.com',
                                         'LLM_USAGE_LOG': str(usage), 'LLM_MODEL': 'test-model'}, clear=True), \
                    patch.object(llm_common, '_DOTENV_LOADED', True), \
                    patch.object(llm_common.urllib.request, 'urlopen', side_effect=exc) as mock:
                with self.assertRaisesRegex(LLMRequestError, 'authentication') as caught:
                    llm_common.call_llm(TX, 'private-system', 'private-article-body', operation='company')
            log = usage.with_name('usage-failures.jsonl').read_text(encoding='utf-8')
            self.assertEqual(len(log.splitlines()), 1)
            self.assertEqual(json.loads(log)['error']['httpStatus'], 401)
            self.assertEqual(mock.call_count, 1)
            self.assertNotIn('private', log + str(caught.exception))
            self.assertNotIn('secret', log + str(caught.exception))
            self.assertNotIn('fake-key', log)
            self.assertFalse(usage.exists())

    def test_invalid_success_envelope_is_classified(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"choices":[],"usage":{"total_tokens":7}}'
        with tempfile.TemporaryDirectory() as temp:
            model = TX['model']
            with patch.dict(os.environ, {model['api_key_env']: 'fake-key',
                                         model['api_base_env']: 'https://example.com',
                                         'LLM_USAGE_LOG': str(Path(temp)/'usage.jsonl')}, clear=True), \
                    patch.object(llm_common, '_DOTENV_LOADED', True), \
                    patch.object(llm_common.urllib.request, 'urlopen', return_value=Response()):
                with self.assertRaisesRegex(LLMRequestError, 'invalid_response'):
                    llm_common.call_llm(TX, 'system', 'user')
            self.assertEqual(json.loads((Path(temp)/'usage.jsonl').read_text())['usage']['total_tokens'], 7)
            self.assertEqual(json.loads((Path(temp)/'usage-failures.jsonl').read_text())['error']['category'], 'invalid_response')

    def test_content_failures_do_not_open_circuit_and_success_resets(self):
        circuit = FailureCircuit()
        content = {'status': 'failed', 'error': safe_error(LLMRequestError('content'))}
        failed = {'status': 'failed', 'error': safe_error(TimeoutError('secret'))}
        for _ in range(10):
            circuit.observe(content)
        self.assertFalse(circuit.stopped)
        self.assertEqual(circuit.failure_count, 0)
        circuit.observe(failed)
        circuit.observe(failed)
        circuit.observe({'status': 'complete'})
        circuit.observe(failed)
        self.assertFalse(circuit.stopped)
        circuit.observe(failed)
        circuit.observe(failed)
        self.assertTrue(circuit.stopped)
        circuit.observe({'status': 'complete'})
        self.assertTrue(circuit.stopped)


class BoundedExtractionTest(unittest.TestCase):
    def test_company_authentication_failure_stops_queue_and_saves_reason(self):
        tx = copy.deepcopy(TX)
        tx['companyOverview'] = {'concurrency': 2, 'max_new_articles_per_run': 50}
        calls = []
        def llm(*args, **kwargs):
            calls.append(1)
            raise urllib.error.HTTPError('https://example.com', 401, 'private-secret', {}, None)
        with tempfile.TemporaryDirectory() as temp:
            results, cost = companies.extract_articles(tx, articles(20), Path(temp)/'cache.json', llm)
            self.assertLessEqual(len(calls), 2)
            self.assertTrue(cost['circuitOpen'])
            self.assertEqual(cost['modelSuccesses'], 0)
            self.assertEqual(cost['modelCalls'], len(calls))
            self.assertEqual(cost['articlesDeferred'], 20-len(calls))
            self.assertEqual(len(results), 20)
            log = (Path(temp)/'cache_failures.json').read_text(encoding='utf-8')
            self.assertNotIn('private-secret', log)
            self.assertIn('authentication', log)

    def test_repeated_company_protocol_failures_stop_with_bounded_inflight(self):
        tx = copy.deepcopy(TX)
        tx['companyOverview'] = {'concurrency': 2, 'max_new_articles_per_run': 50}
        calls = []
        def llm(*args, **kwargs):
            calls.append(1)
            return 'not-json'
        with tempfile.TemporaryDirectory() as temp:
            _, cost = companies.extract_articles(tx, articles(20), Path(temp)/'cache.json', llm)
        self.assertGreaterEqual(len(calls), 3)
        self.assertLessEqual(len(calls), 4)
        self.assertTrue(cost['circuitOpen'])

    def test_funding_stops_queue_and_preserves_paid_success(self):
        tx = copy.deepcopy(TX)
        tx['funding']['concurrency'] = 2
        tx['funding']['budget_seconds'] = 60
        import threading
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        calls = []
        def llm(*args, **kwargs):
            with lock:
                calls.append(1)
                number = len(calls)
            barrier.wait(timeout=2)
            if number == 1:
                raise LLMRequestError('authentication', 401)
            return '{"companies":[]}'
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'cache.json'
            with self.assertRaisesRegex(ValueError, '融资模型阶段停止'):
                funding.extract_articles(tx, articles(20), target, llm)
            self.assertLessEqual(len(calls), 3)
            cache = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(len(cache), 1)
            self.assertTrue((Path(temp)/'cache_failures.json').exists())

    def test_funding_budget_limits_submissions_and_drains_running_calls(self):
        tx = copy.deepcopy(TX)
        tx['funding'].update(concurrency=2, budget_seconds=0)
        calls = []
        def llm(*args, **kwargs):
            calls.append(1)
            return '{"companies":[]}'
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'cache.json'
            results = funding.extract_articles(tx, articles(20), target, llm)
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(json.loads(target.read_text())), 2)
            self.assertEqual(sum(r['status'] == 'pending' for r in results.values()), 18)

    def test_funding_cached_success_cannot_hide_all_new_failures(self):
        replies = iter(['{"companies":[]}', 'invalid'])
        def llm(*args, **kwargs):
            return next(replies)
        with tempfile.TemporaryDirectory() as temp, patch.object(funding_table, 'load_articles', return_value=articles(2)):
            root = Path(temp)
            tx = copy.deepcopy(TX)
            tx['funding']['concurrency'] = 1
            args = (root/'snapshot.json', root/'feed.json', root/'work', tx, root/'cache')
            table = funding_table.build_funding_table(*args, llm_fn=llm, skip_search=True)
            self.assertEqual(table['stats']['modelSuccesses'], 1)
            with self.assertRaisesRegex(ValueError, '新请求全部失败'):
                funding_table.build_funding_table(*args, llm_fn=lambda *a, **kw: 'invalid', skip_search=True)


if __name__ == '__main__':
    unittest.main()
