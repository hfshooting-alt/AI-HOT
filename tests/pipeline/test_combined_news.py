"""No network/model calls: independent branches, honest partial coverage and unified processing."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent))
from _tempdir import make_temp_dir
import news_pipeline as news
import build_snapshot as snapshot
import screen_news
import enrich_news
from automation import runner, publish
from manus_source.config import load_sources
from manus_source.window import ten_am_window

DATE = '2026-09-10'


def screen(items, *args, **kwargs):
    return ({screen_news.item_key(i): {'status': 'complete', 'relevant': True} for i in items},
            {'input': len(items), 'relevant': len(items), 'irrelevant': 0, 'failed': 0, 'pending': 0})


def enrich(items, *args):
    return {enrich_news.enrich_item_key(i): {'enrichmentStatus': 'complete', 'summary': '可溯源事实摘要。' * 12,
            'classification': {'category': 'general', 'tags': {}, 'autoFallback': False, 'autoFilled': []}}
            for i in items}


class CombinedNews(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir('combined-news-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        env = patch.dict(os.environ, {'AIHOT_CUTOFF_TIME': '09:30'})
        env.start()
        self.addCleanup(env.stop)
        self.workspace = self.root / 'run/workspace'
        self.raw = self.root / 'manus'
        self.groups = load_sources(ROOT / 'config/manus_sources.json')
        self.item = {'id': 'example', 'title': '测试公司发布新的AI产品', 'summary': '公开信息描述产品功能。' * 15,
                     'url': 'https://example.com/article', 'source': '测试来源',
                     'publishedAt': '2026-09-10T08:00:00+08:00'}
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'success'}}})
        publish.save(self.workspace / 'inputs/aihot.json', {'collectionWindow': ten_am_window(DATE), 'items': [self.item]})

    def process(self, **kwargs):
        return news.process(DATE, self.workspace, self.raw, screen_fn=screen, enrich_fn=enrich, **kwargs)

    def manus_sample(self):
        for group, sources in self.groups.items():
            data = {'schema_version': 3, 'source_group': group, 'target_date': DATE,
                    'collectionWindow': ten_am_window(DATE), 'articles': [], 'source_audits': [
                        {'account_name': s['account_name'], 'source_status': 'complete', 'article_count': 0, 'note': None}
                        for s in sources]}
            if group == 'group_a':
                s = sources[0]
                art = {'account_name': s['account_name'], 'source_platform': s['platform'], 'source_home_url': s['home_url'],
                       'title': self.item['title'], 'article_url': self.item['url'], 'published_date': DATE,
                       'published_at': self.item['publishedAt'], 'author': None, 'extraction_status': 'complete', 'note': None}
                data['articles'] = [art]
                data['source_audits'][0]['article_count'] = 1
                publish.save(self.raw / DATE / 'raw/content-batch-01.json', {'target_date': DATE, 'articles': [
                    {**art, 'content_text': '这是经过验证的文章正文。' * 30, 'content_status': 'complete',
                     'content_truncated': False}]})
            publish.save(self.raw / DATE / 'raw' / f'discovery-{group}.json', data)

    def test_manus_failure_keeps_aihot_and_never_injects_old_feed(self):
        publish.save(self.workspace / 'data/manus/current.json', {'ok': True, 'items': [{'id': 'old'}]})
        result = self.process()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['collector'], 'aihot')
        self.assertTrue(result['collectionStatus']['degraded'])
        self.assertEqual(news.read(self.workspace / 'data/manus/current.json')['items'], [])

    def test_aihot_failure_keeps_verified_manus(self):
        self.manus_sample()
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'failed'}}})
        result = self.process()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['collector'], 'manus')
        self.assertEqual(result['collectionStatus']['sources'][0]['status'], 'failed')

    def test_duplicate_across_branches_processed_once_with_body(self):
        self.manus_sample()
        result = self.process()
        self.assertEqual(result['collectionStatus']['candidateArticles'], 1)
        self.assertEqual(result['items'][0]['evidenceKind'], 'article_body')
        self.assertEqual(len(result['items'][0]['sourceRefs']), 2)
        self.assertNotIn('content_text', result['items'][0])

    def test_all_sources_failed_blocks_publication(self):
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'failed'}}})
        with self.assertRaisesRegex(ValueError, 'All sources'):
            self.process()
        self.assertFalse((self.workspace / 'inputs/processed.json').exists())

    def test_aihot_only_keeps_upstream_wechat_and_uses_model(self):
        self.item.update(source='公众号：测试', sourceType='wechat')
        publish.save(self.workspace / 'inputs/aihot.json', {'collectionWindow': ten_am_window(DATE), 'items': [self.item]})
        result = self.process(enabled=False)
        self.assertEqual(result['items'][0]['classification']['category'], 'general')
        self.assertFalse(result['collectionStatus']['degraded'])
        self.assertTrue(all(s['status'] == 'not_requested' for s in result['collectionStatus']['sources'][1:]))

    def test_verified_zero_articles_is_not_failure(self):
        publish.save(self.workspace / 'inputs/aihot.json', {'collectionWindow': ten_am_window(DATE), 'items': []})
        result = self.process(enabled=False)
        self.assertEqual(result['items'], [])
        self.assertFalse(result['collectionStatus']['degraded'])

    def test_model_failure_blocks_even_with_successful_source(self):
        def failed(items, *args, **kwargs):
            return {}, {'irrelevant': 0}
        with self.assertRaisesRegex(ValueError, 'relevance'):
            news.process(DATE, self.workspace, self.raw, screen_fn=failed, enrich_fn=enrich)

    def test_wrong_window_cannot_enter_current_batch(self):
        publish.save(self.workspace / 'inputs/aihot.json', {'collectionWindow': {}, 'items': [self.item]})
        with self.assertRaisesRegex(ValueError, 'window'):
            self.process()

    def test_failed_summary_never_publishes_fallback(self):
        with self.assertRaisesRegex(ValueError, 'summary/classification'):
            news.process(DATE, self.workspace, self.raw, screen_fn=screen, enrich_fn=lambda *args: {})

    def test_missing_body_marks_only_that_source_partial(self):
        self.manus_sample()
        (self.raw / DATE / 'raw/content-batch-01.json').unlink()
        result = self.process()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['collector'], 'aihot')
        audit = next(a for a in result['collectionStatus']['sources'] if a['name'] == '游戏葡萄')
        self.assertEqual(audit['status'], 'partial')

    def test_daily_company_inputs_do_not_reintroduce_weekly_exclusions(self):
        from company_index.inputs import load_articles
        current = {'id': 'aihot:new', 'title': '已筛选文章', 'url': 'https://example.com/new'}
        old = {'id': 'aihot:old', 'title': '历史文章', 'url': 'https://example.com/old'}
        publish.save(self.workspace / 'snapshot.json', {'collectionStatus': {'degraded': False},
            'all': {'items': [current]}, 'weekly': {'sections': [{'items': [old]}]}})
        rows = load_articles(self.workspace / 'snapshot.json', self.workspace / 'missing.json', self.raw, {})
        self.assertEqual([r['id'] for r in rows], ['aihot:new'])

    def test_collectors_start_concurrently_and_failure_does_not_skip_news(self):
        (self.root / 'config').mkdir()
        for name in ('taxonomy.json', 'manus_sources.json'):
            shutil.copy(ROOT / 'config' / name, self.root / 'config' / name)
        barrier = threading.Barrier(2, timeout=3)
        calls = []
        def execute(cmd):
            if cmd[1].endswith('runner.py'):
                barrier.wait()
                calls.append('discovery')
                return 1
            if 'collect' in cmd:
                barrier.wait()
                calls.append('aihot')
                return 0
            calls.append('news' if 'process' in cmd else Path(cmd[1]).stem)
            return 0
        with contextlib.redirect_stdout(io.StringIO()):
            code = runner.run(self.root, DATE, list(runner.COMBINED_STAGES), combined=True,
                              ten_am=True, no_promote=True, execute=execute)
        self.assertEqual(code, 0)
        self.assertEqual(set(calls[:2]), {'discovery', 'aihot'})
        self.assertIn('news', calls)

    def test_snapshot_reads_prepared_pool_without_network_or_old_manus(self):
        result = self.process()
        args = ['build_snapshot.py', '--window-date', DATE,
                '--input-json', str(self.workspace / 'inputs/processed.json'), '--no-tags', '--require-tags',
                '--out', str(self.workspace / 'index.html'), '--snapshot-json', str(self.workspace / 'snapshot.json'),
                '--archive-dir', str(self.workspace / 'archive'), '--history-dir', str(self.workspace / 'history'),
                '--weekly-dir', str(self.workspace / 'weekly')]
        for key in ('template', 'history-template', 'weekly-template'):
            name = {'template': 'index', 'history-template': 'history', 'weekly-template': 'weekly'}[key]
            args.extend(['--' + key, str(ROOT / 'scripts/templates' / f'{name}.template.html')])
        args.extend(['--taxonomy', str(ROOT / 'config/taxonomy.json')])
        with patch.object(sys, 'argv', args), patch.object(snapshot, 'fetch_items', side_effect=AssertionError('network')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(snapshot.main(), 0)
        actual = news.read(self.workspace / 'snapshot.json')
        self.assertEqual(actual['collectionStatus'], result['collectionStatus'])
        self.assertEqual(actual['all']['items'][0]['id'], 'aihot:example')

    def test_retry_collector_invalidates_successful_downstream(self):
        calls = []
        def execute(cmd):
            stage = 'aihot' if 'collect' in cmd else 'news' if 'process' in cmd else Path(cmd[1]).stem
            calls.append(stage)
            return 1 if stage == 'runner' else 0
        with contextlib.redirect_stdout(io.StringIO()):
            for resume in (False, True):
                self.assertEqual(runner.run(self.root, DATE, list(runner.COMBINED_STAGES),
                    combined=True, ten_am=True, no_promote=True, resume=resume, execute=execute), 0)
        self.assertEqual(calls.count('aihot'), 1)
        self.assertEqual(calls.count('news'), 2)
        self.assertEqual(calls.count('build_company_overview'), 2)

    def test_failed_discovery_does_not_launch_paid_content(self):
        calls = []
        def execute(cmd):
            calls.append(Path(cmd[1]).stem)
            return 1 if cmd[1].endswith('runner.py') else 0
        with patch.dict(os.environ, {'MANUS_CONTENT_MODE': 'manus'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run(self.root, DATE, list(runner.COMBINED_STAGES),
                combined=True, ten_am=True, no_promote=True, execute=execute), 0)
        self.assertNotIn('content_phase', calls)


if __name__ == '__main__':
    unittest.main()
