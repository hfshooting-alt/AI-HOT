import tempfile
import unittest
from unittest.mock import Mock

from company_index.search import discover, parse_sources


class CompanySearchTest(unittest.TestCase):
    def test_answer_and_tool_intent_are_not_search_evidence(self):
        for raw in ({'choices': [{'message': {'content': 'I searched the web'}}]},
                    {'web_search': []}, {'web_search': {'query': 'search'}}):
            with self.assertRaises(ValueError):
                parse_sources(raw)

    def test_sources_remain_unverified_and_unsafe_urls_are_dropped(self):
        rows = [{'link': url, 'content': 'Evidence'} for url in (
            'https://example.com/legal', 'https://example.com/legal',
            'http://example.com', 'https://user:password@example.com')]
        result = parse_sources({'web_search': rows})
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]['verified'])

    def test_failure_consumes_budget_and_does_not_retry(self):
        tx = {'model': {'api_base_env': 'SEARCH_TEST_UNUSED_BASE', 'default_base': 'https://example.com'}}
        record = {'company_name': 'Example', 'sourceArticles': [{'url': 'https://example.com/news'}]}
        fn = Mock(return_value={'choices': []})
        with tempfile.TemporaryDirectory() as folder:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    discover(tx, record, folder, allow_paid=True, max_requests=1, request_fn=fn)
            other = dict(record, company_name='Another')
            with self.assertRaises(ValueError):
                discover(tx, other, folder, allow_paid=True, max_requests=1, request_fn=fn)
        self.assertEqual(fn.call_count, 1)

    def test_cached_results_reused_without_paid_permission(self):
        tx = {'model': {'api_base_env': 'SEARCH_TEST_UNUSED_BASE', 'default_base': 'https://example.com'}}
        record = {'company_name': 'Example', 'sourceArticles': [{'url': 'https://example.com/news'}]}
        fn = Mock(return_value={'web_search': [{'link': 'https://example.com', 'content': 'Evidence'}]})
        with tempfile.TemporaryDirectory() as folder:
            first = discover(tx, record, folder, allow_paid=True, request_fn=fn)
            second = discover(tx, record, folder, request_fn=fn)
        self.assertEqual(first, second)
        self.assertEqual(fn.call_count, 1)
        self.assertFalse(first['searchFeeKnown'])
