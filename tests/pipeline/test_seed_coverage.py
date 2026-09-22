"""Known seed gaps cannot masquerade as full source coverage; entirely offline."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from manus_source import contracts, runner
from manus_source.client import CreatedTask, ManusAPIError, ManusClient
from manus_source.seed_coverage import apply_seed_coverage, article_key
from manus_source.source_seeds import compact_source_seed

SOURCE = {'account_name': '量子位', 'platform': 'Tencent News',
          'home_url': 'https://news.qq.com/omn/author/8QMc3Hle6oMZuDze'}
WINDOW = {'start': '2026-09-21T09:30:00+08:00', 'end': '2026-09-22T09:30:00+08:00',
          'timezone': 'Asia/Shanghai'}
IDS = ('20260921A08ABD00', '20260921A06P6U00', '20260921A051X800', '20260921A04G6100')


def seed():
    return {'hintOnly': True, 'coverageComplete': False, 'status': 'available',
            'source': deepcopy(SOURCE), 'collectionWindow': deepcopy(WINDOW),
            'candidates': [{'title': '标题' + str(n), 'url': 'https://view.inews.qq.com/a/' + ident,
                            'windowHint': 'within_window'} for n, ident in enumerate(IDS)]}


def article(ident=IDS[0]):
    return {'account_name': SOURCE['account_name'], 'source_platform': SOURCE['platform'],
            'source_home_url': SOURCE['home_url'],
            'article_url': 'https://news.qq.com/rain/a/' + ident + '?id=' + ident + '&redirect_pc=1',
            'title': '标题', 'published_at': '2026-09-21T16:14:00+08:00',
            'published_date': '2026-09-21', 'published_time_text': '2026-09-21 16:14',
            'author': None, 'extraction_status': 'complete', 'note': '详情标题下方发布时间'}


def payload(articles=None):
    articles = [article()] if articles is None else articles
    return {'schema_version': 3, 'source_group': 'group_b', 'target_date': '2026-09-22',
            'collectionWindow': deepcopy(WINDOW), 'articles': articles,
            'source_audits': [{'account_name': SOURCE['account_name'], 'source_status': 'complete',
                               'article_count': len(articles), 'note': '核验通过'}]}


class SeedCoverageTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'AIHOT_CUTOFF_TIME': '09:30'})
        env.start()
        self.addCleanup(env.stop)

    def apply(self, value=None, hints=None):
        hints = seed() if hints is None else hints
        return apply_seed_coverage(hints, compact_source_seed(hints, 2),
                                   payload() if value is None else value, SOURCE, WINDOW)

    def test_actual_four_hint_one_article_shape_is_partial_with_separate_gaps(self):
        hints, value = seed(), payload()
        before = deepcopy((hints, value))
        result, audit = self.apply(value, hints)
        self.assertEqual(result['source_audits'][0]['source_status'], 'partial')
        self.assertEqual(result['articles'], value['articles'])
        self.assertEqual(result['source_audits'][0]['article_count'], 1)
        self.assertEqual((audit['providedHints'], audit['omittedHints'], audit['acceptedHints']), (2, 2, 1))
        self.assertEqual((audit['unresolvedProvided'], audit['unresolvedOmitted']), (1, 2))
        self.assertIn('不代表已确认漏收或可入库文章', result['source_audits'][0]['note'])
        self.assertEqual((hints, value), before)
        self.assertFalse(audit['coverageVerified'])
        contracts.validate_discovery(result, 'group_b', '2026-09-22', ['量子位'])

    def test_zero_accepted_with_hints_is_failed_without_placeholder_articles(self):
        result, audit = self.apply(payload([]))
        self.assertEqual(result['source_audits'][0]['source_status'], 'failed')
        self.assertEqual(result['articles'], [])
        self.assertEqual(audit['unresolvedHints'], 4)
        contracts.validate_discovery(result, 'group_b', '2026-09-22', ['量子位'])

    def test_all_matched_does_not_establish_full_window_coverage(self):
        value = payload([article(ident) for ident in IDS])
        result, audit = self.apply(value)
        self.assertEqual(result, value)
        self.assertEqual(audit['unresolvedHints'], 0)
        self.assertFalse(audit['coverageVerified'])

    def test_unbound_or_empty_seed_never_claims_coverage_or_changes_other_source(self):
        for hints in (dict(seed(), source={**SOURCE, 'account_name': 'other'}),
                      dict(seed(), collectionWindow={**WINDOW, 'end': '2026-09-23T09:30:00+08:00'}),
                      dict(seed(), status='unsupported'), dict(seed(), candidates=[])):
            result, audit = self.apply(hints=hints)
            self.assertEqual(result, payload())
            self.assertFalse(audit['coverageVerified'])

    def test_tencent_route_identity_is_narrow_and_never_rewrites_urls(self):
        original = 'https://view.inews.qq.com/a/' + IDS[0]
        self.assertEqual(article_key(original, SOURCE), article_key(article()['article_url'], SOURCE))
        for changed in ('https://evil.example/a/' + IDS[0],
                        'https://view.inews.qq.com.evil.example/a/' + IDS[0],
                        'https://user@view.inews.qq.com/a/' + IDS[0],
                        'https://news.qq.com/rain/a/' + IDS[1],
                        'https://news.qq.com/rain/a/' + IDS[0] + '?id=' + IDS[1]):
            self.assertNotEqual(article_key(original, SOURCE), article_key(changed, SOURCE))
        result, _ = self.apply()
        self.assertEqual(result['articles'][0]['article_url'], article()['article_url'])

    def test_foreign_source_and_prose_rejection_do_not_resolve_hints(self):
        value = payload([dict(article(), source_home_url='https://other.example/')])
        value['source_audits'][0]['note'] = '所有候选已核验并排除：' + seed()['candidates'][1]['url']
        _, audit = self.apply(value)
        self.assertEqual(audit['acceptedHints'], 0)
        self.assertEqual(audit['unresolvedHints'], 4)

    def test_duplicate_redirect_aliases_count_as_one_hint(self):
        hints = seed()
        hints['candidates'] = [hints['candidates'][0], {'url': article()['article_url']}]
        result, audit = self.apply(hints=hints)
        self.assertEqual(audit['candidateHints'], 1)
        self.assertEqual(audit['acceptedHints'], 1)
        self.assertEqual(result['source_audits'][0]['source_status'], 'complete')

    def run_mock(self, directory, *, late=False, value=None, expect_audit=True):
        hints = seed()
        raw = payload() if value is None else value
        saved = deepcopy((hints, raw))
        client = ManusClient('offline', 'manus-1.6-lite', 0, 1,
                             require_terminal_confirmation=True, late_result_grace_seconds=15 if late else 0)
        with patch('manus_source.source_seeds.build_source_seed', return_value=hints) as build, \
             patch.object(client, 'create_crawl_task', return_value=CreatedTask('test-task', 'https://example.com/t')) as create, \
             patch.object(client, 'wait_for_structured_result', side_effect=ManusAPIError('stop threshold') if late else None,
                          return_value=raw), \
             patch.object(client, 'stop_task') as stop, \
             patch.object(client, 'confirm_task_stopped', return_value={'confirmed': True, 'remoteStatus': 'stopped'}), \
             patch.object(client, 'read_stopped_results', side_effect=[None, raw] if late else None), \
             patch('manus_source.runner.time.sleep'):
            result = runner.run_discovery(client, 'group_b', '2026-09-22', 'prompt', ['量子位'], WINDOW,
                12, [SOURCE], Path(directory) / 'source.checkpoints.json', use_source_seeds=True)
        self.assertEqual((hints, raw), saved)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(stop.call_count, int(late))
        sent = create.call_args.kwargs['prompt_text']
        self.assertIn(IDS[0], sent)
        self.assertIn(IDS[1], sent)
        self.assertNotIn(IDS[2], sent)
        audit_path = Path(directory) / 'source.checkpoints.seed-coverage.json'
        if not expect_audit:
            self.assertFalse(audit_path.exists())
            return result
        report = json.loads(audit_path.read_text(encoding='utf-8'))
        self.assertEqual(report['taskId'], 'test-task')
        self.assertEqual(report['unresolvedProvided'], 1 if result['articles'] else 2)
        self.assertEqual(report['unresolvedOmitted'], 2)
        self.assertNotIn('articles', report)
        return result

    def test_runner_normal_result_writes_private_audit_and_preserves_raw_input(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_mock(directory)
        self.assertEqual(result['source_audits'][0]['source_status'], 'partial')

    def test_runner_late_recovered_final_cannot_bypass_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_mock(directory, late=True)
        self.assertEqual(result['source_audits'][0]['source_status'], 'partial')

    def test_runner_late_empty_complete_with_unresolved_hints_becomes_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_mock(directory, late=True, value=payload([]))
        self.assertEqual(result['source_audits'][0]['source_status'], 'failed')

    def test_outside_original_time_is_not_promoted_from_a_matching_seed(self):
        invalid = dict(article(), published_at='2026-09-21T09:00:00+08:00',
                       published_time_text='2026-09-21 09:00')
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_mock(directory, value=payload([invalid]))
        self.assertEqual(result['articles'], [])
        self.assertEqual(result['source_audits'][0]['source_status'], 'failed')

    def test_private_audit_write_failure_cannot_restore_complete(self):
        original_write = Path.write_text
        for error_type in (OSError, RuntimeError):
            with self.subTest(error_type=error_type.__name__):
                def write(path, *args, **kwargs):
                    if path.name.endswith('.seed-coverage.tmp'):
                        raise error_type('offline diagnostic failure')
                    return original_write(path, *args, **kwargs)
                with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'write_text', write), \
                     patch('builtins.print') as notice:
                    result = self.run_mock(directory, expect_audit=False)
                self.assertEqual(result['source_audits'][0]['source_status'], 'partial')
                expected = 'audit persistence failed: ' + error_type.__name__
                self.assertTrue(any(expected in str(call) for call in notice.call_args_list))

    def test_failed_task_without_final_keeps_private_hint_gap_and_original_error(self):
        client = ManusClient('offline', 'manus-1.6-lite', 0, 1)
        with tempfile.TemporaryDirectory() as directory, \
             patch('manus_source.source_seeds.build_source_seed', return_value=seed()), \
             patch.object(client, 'create_crawl_task', return_value=CreatedTask('test-task', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=ManusAPIError('original failure')), \
             patch.object(client, 'stop_task'), patch.object(client, 'read_stopped_results', return_value=None), \
             patch.object(client, 'confirm_task_stopped', return_value={'confirmed': True, 'remoteStatus': 'stopped'}):
            with self.assertRaisesRegex(runner.DiscoveryRunError, 'original failure') as caught:
                runner.run_discovery(client, 'group_b', '2026-09-22', 'prompt', ['量子位'], WINDOW,
                    12, [SOURCE], Path(directory) / 'source.checkpoints.json', use_source_seeds=True)
            self.assertIsNone(caught.exception.partial_payload)
            audit = json.loads((Path(directory) / 'source.checkpoints.seed-coverage.json').read_text(encoding='utf-8'))
            self.assertEqual(audit['effectiveStatus'], 'failed')
            self.assertEqual(audit['unresolvedHints'], 4)


if __name__ == '__main__':
    unittest.main()
