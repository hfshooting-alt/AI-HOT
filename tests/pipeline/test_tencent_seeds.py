"""Tencent hints must never turn source/time metadata into admitted news."""
import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from manus_source import tencent_seeds as seeds
from manus_source.window import BJ

SOURCE = {'account_name': '极客公园', 'platform': 'Tencent News',
          'home_url': 'https://news.qq.com/omn/author/8QMX2ndU7oYcuTc%3D?tab=om_index'}
WINDOW = {'start': '2026-09-21T09:30:00+08:00', 'end': '2026-09-22T09:30:00+08:00', 'timezone': 'Asia/Shanghai'}
NOW = datetime(2026, 9, 22, 16, 45, tzinfo=BJ)


def row(ident='20260922A02N9C00', when='2026-09-22 08:44:08', **changes):
    value = {'id': ident, 'title': '一篇公开文章', 'url': f'https://view.inews.qq.com/a/{ident}',
             'time': when, 'chlname': '极客公园',
             'card': {'chlname': '极客公园', 'suid': '8QMX2ndU7oYcuTc='}}
    value.update(changes)
    return value


def payload(rows, **changes):
    return json.dumps({'ret': 0, 'newslist': rows, 'hasNext': 1, **changes}, ensure_ascii=False).encode()


class TencentSeeds(unittest.TestCase):
    def build(self, rows=None, transport=None, source=None):
        transport = transport or (lambda req, *_: (200, req.full_url, payload(rows or [])))
        return seeds.build_tencent_seed(source or SOURCE, WINDOW, transport=transport, now_fn=lambda: NOW)

    def test_actual_legacy_card_shape_provides_hints_never_discovery_or_coverage(self):
        result = self.build([row(timestamp=1790037848)])
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['requestsAttempted'], 1)
        hint, = result['candidates']
        self.assertEqual(hint['listTimeText'], '2026-09-22 08:44:08')
        self.assertEqual(hint['rawPublishTime'], '')
        self.assertEqual(hint['windowHint'], 'within_window')
        self.assertEqual(hint['cardSuid'], '8QMX2ndU7oYcuTc=')
        self.assertEqual(hint['listObservedAt'], NOW.isoformat())
        self.assertNotIn('publishedAt', hint)
        self.assertFalse(hint['originalPublicationVerified'])
        self.assertTrue(hint['requiresManusVerification'])
        self.assertTrue(result['hintOnly'])
        self.assertFalse(result['coverageComplete'])
        self.assertFalse(result['identityVerified'])
        self.assertNotIn('articles', result)
        self.assertNotIn('source_status', result)

    def test_single_anonymous_get_exact_public_parameters_and_limits(self):
        calls = []
        def transport(req, timeout, cap):
            calls.append(req)
            self.assertEqual(req.get_method(), 'GET')
            self.assertIsNone(req.data)
            self.assertEqual((timeout, cap), (15, 1024 * 1024))
            self.assertEqual(urlsplit(req.full_url).hostname, 'i.news.qq.com')
            self.assertEqual(parse_qs(urlsplit(req.full_url).query, keep_blank_values=True), {
                'offset_info': [''], 'guestSuid': ['8QMX2ndU7oYcuTc='], 'tabId': ['om_article'],
                'caller': ['1'], 'from_scene': ['103']})
            headers = {key.lower(): value for key, value in req.header_items()}
            self.assertNotIn('cookie', headers)
            self.assertNotIn('authorization', headers)
            return 200, req.full_url, payload([row()])
        self.build(transport=transport)
        self.assertEqual(len(calls), 1)

    def test_fixed_window_start_inclusive_end_exclusive_all_observations_retained(self):
        result = self.build([row(f'20260921A0000{i}00', when) for i, when in enumerate([
            '2026-09-21 09:29:59', '2026-09-21 09:30:00', '2026-09-22 09:29:59', '2026-09-22 09:30:00'])])
        self.assertEqual(len(result['observations']), 4)
        self.assertEqual([x['windowHint'] for x in result['observations']],
                         ['before_window', 'within_window', 'within_window', 'after_window'])
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(result['boundary']['observedListOrder'], 'out_of_order')
        self.assertEqual(result['boundary']['ordering'], 'unverified')

    def test_absolute_timestamp_or_date_takes_precedence_over_yesterday(self):
        rows = [row('20260921A0000100', '昨天', publish_time='2026-09-21 08:00:00'),
                row('20260921A0000200', '2026-09-20 20:00:00', publish_time='昨天'),
                row('20260921A0000300', '昨天', timestamp=int(datetime(2026, 9, 22, 12, tzinfo=BJ).timestamp())),
                row('20260921A0000400', '昨天', publish_time='2026-09-20'),
                row('20260921A0000500', '昨天'), row('20260921A0000600', '2026-09-21')]
        result = self.build(rows)
        self.assertEqual([x['windowHint'] for x in result['observations']],
                         ['before_window', 'before_window', 'after_window', 'before_window',
                          'yesterday_exception_hint', 'overlaps_boundary'])
        self.assertEqual([x['id'] for x in result['candidates']], [rows[4]['id'], rows[5]['id']])
        self.assertNotIn('listDisplayedAt', result['observations'][4])

    def test_priority_preserves_unknowns_without_misleading_chronological_sort(self):
        result = self.build([row('20260921A0000100', '?'), row('20260921A0000200', '昨天'),
                             row('20260921A0000300', '2026-09-21 12:00:00')])
        self.assertEqual([x['windowHint'] for x in result['candidates']],
                         ['within_window', 'yesterday_exception_hint', 'unknown'])
        self.assertEqual([x['listIndex'] for x in result['observations']], [0, 1, 2])

    def test_conflicting_absolute_times_are_unresolved_not_replaced_by_relative_label(self):
        result = self.build([row(publish_time='2026-09-20 08:00:00')])
        hint, = result['candidates']
        self.assertEqual(hint['windowHint'], 'unknown')
        self.assertTrue(hint['listTimeConflict'])
        self.assertFalse(hint['originalPublicationVerified'])

    def test_source_binding_requires_configured_id_and_both_allowed_display_names(self):
        rows = [row('20260921A0000100', card={'suid': 'other', 'chlname': '极客公园'}),
                row('20260921A0000200', chlname='未知转载账号'),
                row('20260921A0000300', card={'suid': '8QMX2ndU7oYcuTc=', 'chlname': ''}),
                row('20260921A0000400')]
        result = self.build(rows)
        self.assertEqual(result['rejectedRows'], 3)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([x['id'] for x in result['candidates']], ['20260921A0000400'])
        self.assertEqual(len(result['observations']), 4)
        for bad in result['observations'][:3]:
            self.assertIn('source_binding_unverified', bad['rejectionReasons'])

    def test_observed_aliases_allowed_only_for_their_exact_configured_author(self):
        cases = [('瑞恩资本', '8QMY33Zd7YwduQ==', '瑞恩资本RyanBenCapital'),
                 ('ZPotential', '8QIf3nxd5YwYvz/c5wM=', 'ZPotentials')]
        from urllib.parse import quote
        for name, suid, alias in cases:
            source = {'account_name': name, 'platform': 'Tencent News',
                      'home_url': 'https://news.qq.com/omn/author/' + quote(suid, safe='') + '?tab=om_article'}
            result = self.build([row(chlname=alias, card={'suid': suid, 'chlname': alias})], source=source)
            self.assertEqual(len(result['candidates']), 1)

    def test_bad_source_urls_and_unknown_accounts_do_not_attempt_requests(self):
        values = ['http://news.qq.com/omn/author/8QMX2ndU7oYcuTc=',
                  'https://news.qq.com.evil/omn/author/8QMX2ndU7oYcuTc=',
                  'https://user:pass@news.qq.com/omn/author/8QMX2ndU7oYcuTc=',
                  SOURCE['home_url'] + '&url=http://localhost',
                  'https://news.qq.com/omn/author/different?tab=om_article']
        for source in [{**SOURCE, 'home_url': url} for url in values] + [{**SOURCE, 'account_name': 'other'}]:
            with patch.object(seeds, '_fetch', side_effect=AssertionError('network forbidden')):
                result = seeds.build_tencent_seed(source, WINDOW)
                self.assertEqual(result['requestsAttempted'], 0)

    def test_response_urls_cannot_create_ssrf_or_leak_query_credentials(self):
        unsafe = ['http://127.0.0.1/private', 'https://news.qq.com.evil/a/20260922A02N9C00',
                  'https://secret@view.inews.qq.com/a/20260922A02N9C00',
                  'https://view.inews.qq.com/a/DIFFERENT']
        for url in unsafe:
            result = self.build([row(url=url)])
            self.assertEqual(result['candidates'], [])
            self.assertEqual(result['observations'][0]['url'], '')
        result = self.build([row(url=row()['url'] + '?signature=PRIVATE_TOKEN#PRIVATE_FRAGMENT')])
        self.assertEqual(result['candidates'][0]['url'], row()['url'])
        self.assertNotIn('PRIVATE_', json.dumps(result))

    def test_empty_and_all_outside_list_do_not_mean_no_updates_or_complete_coverage(self):
        for rows in ([], [row(when='2026-09-10 12:00:00')]):
            result = self.build(rows)
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['candidates'], [])
            self.assertIn('no_candidates_does_not_mean_no_articles', result['warnings'])
            self.assertFalse(result['coverageComplete'])

    def test_invalid_schema_blocking_and_oversize_stop_after_one_request(self):
        cases = [(200, b'[]', 'list_schema_unverified'),
                 (200, payload([], ret=False), 'list_schema_unverified'),
                 (200, payload([row()] * 21), 'list_schema_unverified'),
                 (200, b'x' * (seeds.MAX_BYTES + 1), 'response_size_limit'),
                 (200, b'<title>CAPTCHA</title>', 'security_verification'),
                 (403, b'PRIVATE_RESPONSE', 'http_403')]
        for status, body, reason in cases:
            calls = []
            def transport(req, *_):
                calls.append(req)
                return status, req.full_url, body
            result = self.build(transport=transport)
            self.assertEqual(result['stopReason'], reason)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['candidates'], [])
            self.assertNotIn('PRIVATE_RESPONSE', json.dumps(result))
        for error in (TimeoutError('PRIVATE'), URLError('PRIVATE'),
                      HTTPError('https://private', 429, 'PRIVATE', {}, None)):
            result = self.build(transport=MagicMock(side_effect=error))
            self.assertEqual(result['requestsAttempted'], 1)
            self.assertNotIn('PRIVATE', json.dumps(result))

    def test_no_redirect_even_same_host(self):
        result = self.build(transport=lambda req, *_: (200, seeds.TENCENT_LIST, payload([row()])))
        self.assertEqual(result['stopReason'], 'redirect_rejected')
        with self.assertRaisesRegex(seeds.SeedError, 'redirect_rejected'):
            seeds._NoRedirect().redirect_request(None, None, 302, '', {}, seeds.TENCENT_LIST)

    def test_duplicate_cards_kept_as_observations_not_duplicate_candidates(self):
        result = self.build([row(), row()])
        self.assertEqual(len(result['observations']), 2)
        self.assertEqual(len(result['candidates']), 1)
        self.assertTrue(result['observations'][1]['duplicateListRow'])

    def test_no_body_prompt_or_server_exception_leaks_and_inputs_unchanged(self):
        source, window = copy.deepcopy(SOURCE), copy.deepcopy(WINDOW)
        data = payload([row(content='PRIVATE_BODY', abstract='PRIVATE_ABSTRACT', cookie='PRIVATE_COOKIE')])
        result = seeds.build_tencent_seed(source, window, now_fn=lambda: NOW,
            transport=lambda req, *_: (200, req.full_url, data))
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertEqual(source, SOURCE)
        self.assertEqual(window, WINDOW)

    def test_default_transport_disables_proxies_and_rechecks_read_deadline(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status, response.geturl.return_value = 200, seeds.TENCENT_LIST
        response.read1.side_effect = [b'12345', b'678901']
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(seeds, 'build_opener', return_value=opener) as factory:
            _, _, body = seeds._fetch(Request(seeds.TENCENT_LIST), 15, 10)
        self.assertEqual(len(body), 11)
        self.assertEqual(factory.call_args.args[0].proxies, {})
        self.assertIsInstance(factory.call_args.args[1], seeds._NoRedirect)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 15)
        self.assertEqual([x.args[0] for x in response.read1.call_args_list], [11, 6])
        response.read1.reset_mock(side_effect=True)
        response.read1.return_value = b'x'
        with patch.object(seeds, 'build_opener', return_value=opener), \
             patch.object(seeds.time, 'monotonic', side_effect=[0, 1, 16]):
            with self.assertRaisesRegex(seeds.SeedError, 'request_timeout'):
                seeds._fetch(Request(seeds.TENCENT_LIST), 15, 100)
        self.assertEqual(response.read1.call_count, 1)
        response.fp.raw._sock.settimeout.assert_called_with(14)


if __name__ == '__main__':
    unittest.main()
