"""Anonymous source hints stay bounded, non-authoritative and safe to replay."""
import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.request import Request
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from manus_source import source_seeds as seeds
from manus_source.window import BJ

SOURCE = {'account_name': '白鲸出海', 'platform': 'Official Baijing', 'home_url': seeds.BAIJING_HOME}
WINDOW = {'start': '2026-09-21T09:30:00+08:00', 'end': '2026-09-22T09:30:00+08:00', 'timezone': 'Asia/Shanghai'}
NOW = datetime(2026, 9, 22, 16, 2, 35, tzinfo=BJ)
FIXTURES = ROOT / 'tests/fixtures/source_seeds'


def listing(rows):
    return json.dumps({'code': 0, 'success': True, 'data': {'article_list': rows}}).encode()


def header(title, when):
    return f'<div class="mod-head"><h1>{title}</h1><time class="timeago">{when}</time></div>'.encode()


class SourceSeeds(unittest.TestCase):
    def build(self, transport, **kwargs):
        return seeds.build_source_seed(SOURCE, WINDOW, transport=transport, now_fn=lambda: NOW, **kwargs)

    def fixture_transport(self, request, timeout, max_bytes):
        if request.full_url == seeds.BAIJING_LIST:
            if request.data == b'type=0&pn=1':
                data = (FIXTURES / 'baijing-list.json').read_bytes()
            else:
                data = listing([])
        else:
            ident = request.full_url.rsplit('/', 1)[-1]
            data = (FIXTURES / f'baijing-{ident}-header.html').read_bytes()
        return 200, request.full_url, data

    def test_actual_same_one_day_label_straddles_window_and_never_means_complete(self):
        result = self.build(self.fixture_transport)
        self.assertEqual(result['requestsAttempted'], 4)
        self.assertEqual([r['url'] for r in result['candidates']], [seeds.BAIJING_HOME + '56777'])
        self.assertEqual([r['url'] for r in result['excludedByHeaderTime']], [seeds.BAIJING_HOME + '56765'])
        self.assertEqual([r['listTimeText'] for r in result['observations']], ['1 天前', '1 天前'])
        self.assertEqual(result['boundary']['earliestHeaderTime'], '2026-09-20T17:11:00+08:00')
        self.assertTrue(result['boundary']['headerBeforeStartSeen'])
        self.assertFalse(result['coverageComplete'])
        self.assertFalse(result['identityVerified'])
        self.assertTrue(result['hintOnly'])
        self.assertNotIn('source_status', result)
        self.assertNotIn('articles', result)
        self.assertTrue(all(r['requiresManusVerification'] for r in result['observations']))
        self.assertTrue(all(r['originalPublicationVerified'] is False for r in result['observations']))

    def test_unverified_list_labels_preserve_all_observations_and_ambiguous_candidates(self):
        result = self.build(self.fixture_transport, max_pages=1, max_details=0)
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(result['excludedByHeaderTime'], [])
        self.assertEqual(result['boundary']['earliestHeaderTime'], None)
        for item in result['candidates']:
            self.assertEqual(item['windowHint'], 'overlaps_boundary')
            self.assertNotIn('publishedAt', item)
            self.assertNotIn('headerTime', item)
            self.assertEqual(item['listTimeEstimate']['earliest'][:10], '2026-09-20')

    def test_unknown_and_ancient_labels_never_become_authoritative_timestamps(self):
        rows = [{'id': n, 'title': f'标题 {n}', 'add_time': label} for n, label in enumerate(
            ['2026-09-21', '1790000000', '未知', '3 天前', '1 小时前'], 1)]
        result = self.build(lambda req, *a: (200, req.full_url, listing(rows)), max_pages=1, max_details=0)
        self.assertEqual(len(result['observations']), 5)
        self.assertEqual([r['windowHint'] for r in result['observations']], ['unknown', 'unknown', 'unknown', 'before_window', 'after_window'])
        self.assertEqual(len(result['candidates']), 3)
        self.assertEqual(result['excludedByHeaderTime'], [])
        self.assertFalse(result['coverageComplete'])

    def test_page_limit_does_not_early_stop_on_one_old_or_pinned_row(self):
        calls = []
        def transport(req, *args):
            page = int(req.data.decode().split('pn=')[1])
            calls.append(page)
            row = {'id': page, 'title': f'标题{page}', 'add_time': '8 天前' if page == 1 else '20 小时前', 'sort': 9}
            return 200, req.full_url, listing([row])
        result = self.build(transport, max_pages=3, max_details=0)
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(result['stopReason'], 'page_limit')
        self.assertTrue(result['observations'][0]['possiblyPinned'])
        self.assertEqual(result['boundary']['ordering'], 'unverified')

    def test_repeated_page_stops_without_duplicate_candidates_or_coverage_claim(self):
        calls = []
        def transport(req, *args):
            calls.append(req.full_url)
            return 200, req.full_url, listing([{'id': 12, 'title': '重复标题', 'add_time': '20 小时前'}])
        result = self.build(transport, max_pages=6, max_details=0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(result['stopReason'], 'no_new_list_rows')

    def test_repeated_row_within_page_is_deduplicated_and_json_captcha_title_is_not_a_wall(self):
        row = {'id': 1, 'title': 'AI CAPTCHA 研究', 'add_time': '20 小时前'}
        result = self.build(lambda req, *a: (200, req.full_url, listing([row, row])), max_pages=1, max_details=0)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(len(result['candidates']), 1)

    def test_window_start_included_end_excluded_and_bj_timezone_preserved(self):
        rows = [{'id': 1, 'title': '起点', 'add_time': '?'}, {'id': 2, 'title': '终点', 'add_time': '?'}]
        def transport(req, *args):
            body = listing(rows) if req.data else header('起点', '2026-09-21 09:30') if req.full_url.endswith('/1') else header('终点', '2026-09-22 09:30')
            return 200, req.full_url, body
        result = self.build(transport, max_pages=1, max_details=2)
        self.assertEqual([r['title'] for r in result['candidates']], ['起点'])
        self.assertEqual([r['title'] for r in result['excludedByHeaderTime']], ['终点'])
        self.assertEqual(result['candidates'][0]['headerTime']['displayedAt'], '2026-09-21T09:30:00+08:00')

    def test_same_header_title_required_and_unscoped_time_ignored(self):
        with self.assertRaisesRegex(seeds.SeedError, 'title_unverified'):
            seeds.parse_baijing_detail(header('另一篇标题', '2026-09-21 10:00').decode(), '指定标题')
        text = '<h1>指定标题</h1><time class="timeago">2026-09-21 10:00</time>'
        with self.assertRaises(seeds.SeedError):
            seeds.parse_baijing_detail(text, '指定标题')
        text = '<time class="timeago">2026-09-22 23:00</time>' + header('指定标题', '2026-09-21 10:00').decode()
        self.assertEqual(seeds.parse_baijing_detail(text, '指定标题')['displayedTimeText'], '2026-09-21 10:00')

    def test_detail_drift_retains_list_hint_without_publishing_header_time(self):
        def transport(req, *args):
            data = listing([{'id': 1, 'title': '原题', 'add_time': '20 小时前'}]) if req.data else header('不同文章', '2026-09-21 12:00')
            return 200, req.full_url, data
        result = self.build(transport, max_pages=1, max_details=1)
        self.assertEqual(result['candidates'][0]['detailStatus'], 'detail_title_unverified')
        self.assertNotIn('headerTime', result['candidates'][0])

    def test_no_ssrf_from_configuration_or_response_links(self):
        for source in [{**SOURCE, 'home_url': 'http://127.0.0.1'}, {**SOURCE, 'home_url': seeds.BAIJING_HOME + '?url=http://localhost'},
                       {**SOURCE, 'account_name': '其他'}, {**SOURCE, 'platform': 'Tencent News'}]:
            with self.subTest(source=source), patch.object(seeds, '_fetch', side_effect=AssertionError('network forbidden')):
                result = seeds.build_source_seed(source, WINDOW)
                self.assertEqual(result['requestsAttempted'], 0)
        rows = [{'id': '../secret', 'title': '非法ID'}, {'id': 1, 'title': '合法ID', 'article_link': 'http://127.0.0.1/private', 'url': 'https://evil.example', 'add_time': '?'}]
        calls = []
        def transport(req, *args):
            calls.append(req.full_url)
            return 200, req.full_url, listing(rows) if req.data else header('合法ID', '2026-09-21 12:00')
        result = self.build(transport, max_pages=1, max_details=1)
        self.assertEqual(calls, [seeds.BAIJING_LIST, seeds.BAIJING_HOME + '1'])
        self.assertEqual(result['pages'][0]['rejectedRows'], 1)
        self.assertNotIn('127.0.0.1', json.dumps(result))

    def test_request_headers_are_anonymous_and_limits_are_passed(self):
        def transport(req, timeout, max_bytes):
            self.assertEqual(req.get_method(), 'POST')
            self.assertEqual(req.data, b'type=0&pn=1')
            self.assertEqual(timeout, 7)
            self.assertEqual(max_bytes, 1000)
            lowered = {k.lower() for k, v in req.header_items()}
            self.assertNotIn('authorization', lowered)
            self.assertNotIn('cookie', lowered)
            return 200, req.full_url, listing([])
        self.build(transport, max_pages=1, max_details=0, timeout_seconds=7, max_bytes=1000)

    def test_redirect_rejected_even_to_same_domain_and_no_second_request(self):
        for destination in (seeds.BAIJING_HOME, 'http://127.0.0.1/private', 'https://evil.example'):
            calls = []
            def transport(req, *args):
                calls.append(req.full_url)
                return 200, destination, listing([])
            result = self.build(transport)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['stopReason'], 'redirect_rejected')
        with self.assertRaisesRegex(seeds.SeedError, 'redirect_rejected'):
            seeds._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')

    def test_security_challenge_blocks_without_retry_or_detail_attempt(self):
        for body in (b'<title>Just a moment...</title>', '<title>安全验证</title>'.encode(), b'<html>/cdn-cgi/challenge-platform/</html>'):
            calls = []
            def transport(req, *args):
                calls.append(req.full_url)
                return 200, req.full_url, body
            result = self.build(transport)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['stopReason'], 'security_verification')
            self.assertEqual(len(calls), 1)

    def test_size_http_and_network_errors_are_safe_no_retry(self):
        cases = [(lambda req, *a: (200, req.full_url, b'x' * 101), 'response_size_limit'),
                 (lambda req, *a: (403, req.full_url, b'private response'), 'http_403'),
                 (lambda req, *a: (200, req.full_url, b'[]'), 'list_schema_unverified')]
        for transport, code in cases:
            with self.subTest(code=code):
                result = self.build(transport, max_bytes=100)
                self.assertEqual(result['requestsAttempted'], 1)
                self.assertEqual(result['stopReason'], code)
                self.assertNotIn('private response', json.dumps(result))
        for error in (TimeoutError('private'), URLError('private'), HTTPError('https://private', 429, 'private', {}, None)):
            with self.subTest(error=type(error).__name__):
                def transport(*args):
                    raise error
                result = self.build(transport)
                self.assertEqual(result['requestsAttempted'], 1)
                self.assertNotIn('private', json.dumps(result))

    def test_later_failure_preserves_earlier_hints_and_never_claims_empty_coverage(self):
        def transport(req, *args):
            if req.data == b'type=0&pn=1':
                return 200, req.full_url, listing([{'id': 1, 'title': '已得线索', 'add_time': '?'}])
            raise TimeoutError('private')
        result = self.build(transport)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['requestsAttempted'], 2)

    def test_limits_rejected_before_network_and_total_attempts_at_most_six(self):
        for kwargs in ({'max_pages': 4, 'max_details': 3}, {'max_pages': 0}, {'max_bytes': seeds.MAX_BYTES + 1}, {'timeout_seconds': 20}):
            with self.subTest(kwargs=kwargs), patch.object(seeds, '_fetch', side_effect=AssertionError('network forbidden')):
                with self.assertRaises(ValueError):
                    seeds.build_source_seed(SOURCE, WINDOW, **kwargs)
        calls = []
        def transport(req, *args):
            calls.append(req.full_url)
            if req.data:
                n = int(req.data.decode().split('pn=')[1])
                data = listing([{'id': n, 'title': f'标题{n}', 'add_time': '?'}])
            else:
                data = header('标题' + req.full_url.rsplit('/', 1)[1], '2026-09-21 12:00')
            return 200, req.full_url, data
        result = self.build(transport)
        self.assertEqual(len(calls), 6)
        self.assertEqual(result['requestsAttempted'], 6)

    def test_default_transport_bounds_each_read_and_rechecks_deadline(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status, response.geturl.return_value = 200, seeds.BAIJING_LIST
        response.read1.side_effect = [b'x' * 5, b'y' * 6]
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(seeds, 'build_opener', return_value=opener) as factory:
            status, url, body = seeds._fetch(Request(seeds.BAIJING_LIST), 7, 10)
        self.assertEqual(len(body), 11)
        self.assertEqual([call.args[0] for call in response.read1.call_args_list], [11, 6])
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 7)
        self.assertEqual(factory.call_args.args[0].proxies, {})
        self.assertIsInstance(factory.call_args.args[1], seeds._NoRedirect)
        response.read1.reset_mock(side_effect=True)
        response.read1.return_value = b'x'
        with patch.object(seeds, 'build_opener', return_value=opener), \
             patch.object(seeds.time, 'monotonic', side_effect=[0, 0, 8]):
            with self.assertRaisesRegex(seeds.SeedError, 'request_timeout'):
                seeds._fetch(Request(seeds.BAIJING_LIST), 7, 100)
        self.assertEqual(response.read1.call_count, 1)

    def test_sampled_header_order_cannot_certify_sort_order(self):
        rows = [{'id': n, 'title': f'标题{n}', 'add_time': '?'} for n in (1, 2)]
        def transport(req, *args):
            if req.data:
                data = listing(rows)
            else:
                ident = req.full_url.rsplit('/', 1)[1]
                data = header('标题' + ident, '2026-09-21 10:00' if ident == '1' else '2026-09-21 12:00')
            return 200, req.full_url, data
        result = self.build(transport, max_pages=1, max_details=2)
        self.assertEqual(result['boundary']['observedHeaderOrder'], 'out_of_order')
        self.assertEqual(result['boundary']['ordering'], 'unverified')
        self.assertFalse(result['coverageComplete'])

    def test_inputs_unchanged_and_body_never_appears_in_hints(self):
        source, window = copy.deepcopy(SOURCE), copy.deepcopy(WINDOW)
        def transport(req, *args):
            if req.data:
                data = listing([{'id': 1, 'title': '标题', 'add_time': '?', 'synopsis': 'PRIVATE_BODY', 'user_info': {'cookie': 'PRIVATE_COOKIE'}}])
            else:
                data = header('标题', '2026-09-21 12:00') + b'<div class="mod-body">PRIVATE_BODY</div>'
            return 200, req.full_url, data
        result = seeds.build_source_seed(source, window, transport=transport, max_pages=1, max_details=1, now_fn=lambda: NOW)
        self.assertEqual(source, SOURCE)
        self.assertEqual(window, WINDOW)
        self.assertNotIn('PRIVATE_', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
