"""Production Manus-only boundaries: no retired upstream fallback or paid calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
from datetime import datetime
from unittest.mock import patch

import build_snapshot
import news_pipeline
import run_pipeline
from automation import runner


class ManusOnly(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = patch.dict(os.environ, {'NEWS_COLLECTION_END': '2026-09-22T18:27:36+08:00'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root_patch = patch.object(run_pipeline, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def dry_plan(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run_pipeline.main(['run', '--dry-run', *args]), 0)
        return json.loads(output.getvalue())

    def test_default_plan_has_only_manus_and_exact_rolling_window(self):
        result = self.dry_plan()
        self.assertEqual(result['sourceMode'], 'manus-only')
        self.assertEqual(result['parallelCollectors'], ['discovery'])
        self.assertEqual(result['collectionWindow'], {'start': '2026-09-21T18:27:36+08:00',
            'end': '2026-09-22T18:27:36+08:00', 'timezone': 'Asia/Shanghai'})
        self.assertEqual(result['contentMode'], 'script')
        self.assertFalse(any('collect' in row['command'] or row['stage'] == 'aihot' for row in result['stages']))
        self.assertFalse((self.root / 'work').exists())

    def test_full_is_alias_and_zero_limit_reaches_discovery(self):
        result = self.dry_plan('--source-mode', 'full', '--manus-credit-limit', '0')
        self.assertEqual(result['sourceMode'], 'manus-only')
        command = next(r['command'] for r in result['stages'] if r['stage'] == 'discovery')
        self.assertEqual(command[command.index('--credit-limit-per-source') + 1], '0')
        self.assertIn('--incremental-discovery', command)
        self.assertIn('--source-seeds', command)

    def test_retired_modes_rejected_before_execution(self):
        with patch.object(run_pipeline, 'run') as execute, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                run_pipeline.main(['run', '--source-mode', 'aihot-only'])
        execute.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'AIHOT'):
            runner.plan(self.root, self.root / 'candidate', '2026-09-22', source_mode='aihot-only')
        with self.assertRaisesRegex(ValueError, 'AIHOT'):
            runner.run(self.root, '2026-09-22', ['aihot'], execute=lambda _: self.fail('must not run'))

    def test_missing_manus_configuration_blocks_single_collector_pipeline(self):
        checks = [{'check': 'MANUS_API_KEY', 'ok': False, 'detail': 'not configured'}]
        with patch.object(run_pipeline, 'inspect', return_value=checks), patch.object(run_pipeline, 'run') as execute, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_pipeline.main(['run']), 1)
        execute.assert_not_called()

    def test_cli_forces_script_and_restores_callers_environment(self):
        def execute(root, day, stages, **kwargs):
            self.assertEqual(os.environ['MANUS_CONTENT_MODE'], 'script')
            self.assertEqual(os.environ['NEWS_COLLECTION_END'], '2026-09-22T18:27:36+08:00')
            self.assertEqual(day, '2026-09-22')
            return 0
        with patch.dict(os.environ, {'MANUS_CONTENT_MODE': 'manus'}), \
             patch.object(run_pipeline, 'inspect', return_value=[]), patch.object(run_pipeline, 'run', side_effect=execute):
            self.assertEqual(run_pipeline.main(['run']), 0)
            self.assertEqual(os.environ['MANUS_CONTENT_MODE'], 'manus')

    def saved_run(self):
        directory = self.root / 'work/runs/2026-09-22/ten-am'
        run_id = 'a' * 32
        (directory / run_id).mkdir(parents=True)
        (directory / 'latest.json').write_text(json.dumps({'runId': run_id}))
        state = directory / run_id / 'state.json'
        state.write_text(json.dumps({'collectionWindow': {'start': '2026-09-21T11:12:13+08:00',
            'end': '2026-09-22T11:12:13+08:00', 'timezone': 'Asia/Shanghai'}}))
        return state

    def test_resume_restores_original_second_without_rewriting_state(self):
        state = self.saved_run()
        before = state.read_bytes()
        os.environ.pop('NEWS_COLLECTION_END')
        result = self.dry_plan('--resume', '--date', '2026-09-22')
        self.assertEqual(result['collectionWindow']['end'], '2026-09-22T11:12:13+08:00')
        self.assertEqual(state.read_bytes(), before)
        self.assertNotIn('NEWS_COLLECTION_END', os.environ)

    def test_resume_rejects_different_window_before_any_task(self):
        self.saved_run()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.dry_plan('--resume', '--date', '2026-09-22')

    def test_candidate_commands_honor_explicit_window_without_starting_a_new_one(self):
        os.environ.pop('NEWS_COLLECTION_END')
        end = '2026-09-22T18:27:36+08:00'
        def checked(*args):
            self.assertEqual(os.environ.get('NEWS_COLLECTION_END'), end)
            self.assertEqual(run_pipeline.ten_am_window('2026-09-22')['end'], end)
            return (self.root / 'review', {})
        with patch('automation.candidate.prepare', side_effect=checked) as prepare, \
             patch('automation.candidate.promote', side_effect=lambda *args: checked(*args)[1]) as promote, \
             contextlib.redirect_stdout(io.StringIO()):
            for command in ('review-candidate', 'publish-candidate'):
                self.assertEqual(run_pipeline.main([command, '--candidate', str(self.root / 'candidate'),
                                                   '--window-end', end]), 0)
                self.assertNotIn('NEWS_COLLECTION_END', os.environ)
        prepare.assert_called_once()
        promote.assert_called_once()

    def test_candidate_window_conflict_blocks_before_validation_or_publication(self):
        with patch('automation.candidate.prepare') as prepare, patch('automation.candidate.promote') as promote, \
             contextlib.redirect_stderr(io.StringIO()):
            for command in ('review-candidate', 'publish-candidate'):
                with self.assertRaises(SystemExit):
                    run_pipeline.main([command, '--candidate', str(self.root / 'candidate'),
                                       '--window-end', '2026-09-22T18:27:37+08:00'])
        prepare.assert_not_called()
        promote.assert_not_called()

    def test_tencent_alias_query_dedup_keeps_original_url(self):
        original = 'https://view.inews.qq.com/a/20260922A0123400?from=share'
        def article(title, url):
            return {'account_name': '赛博禅心', 'source_platform': 'Tencent News',
                'source_home_url': 'https://news.qq.com/omn/author/example', 'title': title,
                'article_url': url, 'published_date': '2026-09-22',
                'published_at': '2026-09-22T17:00:00+08:00', 'content_text': '正文' * 100}
        rows = news_pipeline.candidates([], [article('标题一', original),
            article('原标题的变体', 'https://news.qq.com/rain/a/20260922A0123400?from=app'),
            article('另一篇', 'https://news.qq.com/rain/a/20260922A0123500')])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['url'], original)
        self.assertEqual(len(rows[0]['sourceRefs']), 2)

    def test_legacy_collection_entry_never_calls_http(self):
        with patch.object(build_snapshot.urllib.request, 'urlopen', side_effect=AssertionError('network')) as http:
            with self.assertRaisesRegex(ValueError, 'AIHOT collection is disabled'):
                news_pipeline.collect('2026-09-22', self.root / 'out.json')
        http.assert_not_called()
        self.assertFalse((self.root / 'out.json').exists())

    def snapshot_args(self):
        project = Path(__file__).resolve().parents[2]
        args = ['build_snapshot.py', '--window-date', '2026-09-22', '--require-tags',
            '--out', str(self.root / 'index.html'), '--snapshot-json', str(self.root / 'snapshot.json'),
            '--archive-dir', str(self.root / 'archive'), '--history-dir', str(self.root / 'history'),
            '--weekly-dir', str(self.root / 'weekly'), '--taxonomy', str(project / 'config/taxonomy.json')]
        for key, name in [('template', 'index'), ('history-template', 'history'), ('weekly-template', 'weekly')]:
            args += ['--' + key, str(project / 'scripts/templates' / (name + '.template.html'))]
        return args

    def test_standalone_snapshot_does_not_backfill_retired_archive_or_retag(self):
        item = {'id': 'manus:current', 'collector': 'manus', 'title': '本批文章', 'source': '测试源',
            'sourceType': 'media', 'sourceChannel': 'media', 'url': 'https://example.com/current',
            'publishedAt': '2026-09-22T17:00:00+08:00', 'summary': '已处理摘要',
            'classification': {'category': 'general', 'tags': {}, 'autoFallback': False}}
        archive = self.root / 'archive'
        archive.mkdir()
        (archive / '2026-09-22.json').write_text(json.dumps({'date': '2026-09-22', 'finalized': False,
            'items': [{**item, 'id': 'aihot:retired', 'collector': 'aihot', 'title': '旧上游',
                       'url': 'https://example.com/old', 'classification': None}]}), encoding='utf-8')
        (self.root / 'snapshot.json').write_text(json.dumps({'dailyReports': {'old': {'private': True}}}))
        with patch.object(sys, 'argv', self.snapshot_args()), \
             patch.object(build_snapshot, 'load_manus_feed', return_value=([item], {'connected': True, 'note': '本批'})), \
             patch.object(build_snapshot, 'tag_archive_days', side_effect=AssertionError('model forbidden')) as tag, \
             patch.object(build_snapshot.urllib.request, 'urlopen', side_effect=AssertionError('HTTP forbidden')) as http, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_snapshot.main(), 0)
        result = json.loads((self.root / 'snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual([i['id'] for i in result['all']['items']], ['manus:current'])
        self.assertEqual(result['daily']['total'], 1)
        self.assertEqual((result['dailyReports'], result['hot']), ({}, {}))
        tag.assert_not_called()
        http.assert_not_called()

    def test_explicit_aihot_prepared_input_is_rejected_before_archives(self):
        path = self.root / 'processed.json'
        path.write_text(json.dumps({'collectionWindow': {'start': '2026-09-21T18:27:36+08:00',
            'end': '2026-09-22T18:27:36+08:00', 'timezone': 'Asia/Shanghai'},
            'items': [{'id': 'aihot:old', 'collector': 'aihot'}]}))
        with patch.object(sys, 'argv', self.snapshot_args() + ['--input-json', str(path)]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build_snapshot.main(), 1)
        self.assertFalse((self.root / 'archive').exists())

    def test_empty_archive_clears_stale_weekly_outputs_without_date_underflow(self):
        folder = self.root / 'weekly'
        folder.mkdir()
        for suffix in ('.html', '.json'):
            (folder / ('2026-09-07' + suffix)).write_text('old')
        now = datetime(2026, 9, 22, tzinfo=build_snapshot.BJ)
        with patch.object(build_snapshot, 'render', side_effect=AssertionError('no weekly data')):
            nav = build_snapshot.build_weekly_journals({}, str(folder), 'unused', now, now)
        self.assertEqual(nav, [])
        self.assertEqual(list(folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
