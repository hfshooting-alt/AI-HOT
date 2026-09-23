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
from aihot_window import in_window as aihot_in_window
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
        self.manus_sample()

    def process(self, **kwargs):
        return news.process(DATE, self.workspace, self.raw, screen_fn=screen, enrich_fn=enrich, **kwargs)

    def manus_sample(self, items=None):
        items = [self.item] if items is None else items
        for group, sources in self.groups.items():
            data = {'schema_version': 3, 'source_group': group, 'target_date': DATE,
                    'collectionWindow': ten_am_window(DATE), 'articles': [], 'source_audits': [
                        {'account_name': s['account_name'], 'source_status': 'complete', 'article_count': 0, 'note': None}
                        for s in sources]}
            if group == 'group_a':
                s = sources[0]
                arts = [{'account_name': s['account_name'], 'source_platform': s['platform'], 'source_home_url': s['home_url'],
                       'title': item['title'], 'article_url': item['url'], 'published_date': item['publishedAt'][:10],
                       'published_at': item['publishedAt'], 'author': None, 'extraction_status': 'complete', 'note': None}
                        for item in items]
                data['articles'] = arts
                data['source_audits'][0]['article_count'] = len(arts)
                publish.save(self.raw / DATE / 'raw/content-batch-01.json', {'target_date': DATE, 'articles': [
                    {**art, 'content_text': '这是经过验证的文章正文。' * 30, 'content_status': 'complete',
                     'content_truncated': False} for art in arts]})
            publish.save(self.raw / DATE / 'raw' / f'discovery-{group}.json', data)

    def test_manus_failure_never_injects_aihot_or_old_feed(self):
        publish.save(self.workspace / 'data/manus/current.json', {'ok': True, 'items': [{'id': 'old'}]})
        shutil.rmtree(self.raw)
        with self.assertRaisesRegex(ValueError, 'All sources'):
            self.process()
        self.assertFalse((self.workspace / 'inputs/processed.json').exists())
        self.assertEqual(news.read(self.workspace / 'data/manus/current.json')['items'], [{'id': 'old'}])

    def test_aihot_failure_keeps_verified_manus(self):
        self.manus_sample()
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'failed'}}})
        result = self.process()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['collector'], 'manus')
        self.assertTrue(all(a['collector'] == 'manus' for a in result['collectionStatus']['sources']))

    def test_duplicate_across_branches_processed_once_with_body(self):
        self.manus_sample()
        result = self.process()
        self.assertEqual(result['collectionStatus']['candidateArticles'], 1)
        self.assertEqual(result['items'][0]['evidenceKind'], 'article_body')
        self.assertEqual(len(result['items'][0]['sourceRefs']), 1)
        self.assertNotIn('content_text', result['items'][0])

    def set_manus_yesterday(self, *, conflict=False, duplicate=False):
        self.manus_sample()
        fields = {'published_at': '2026-09-09', 'published_date': '2026-09-09',
                  'publishedPrecision': 'date', 'published_time_text': '昨天',
                  'timeEvidence': {'originalText': '昨天', 'observedAt': '2026-09-10T14:00:00+08:00'}}
        if not duplicate:
            fields.update(title='另一篇只有日期精度的报道', article_url='https://example.com/yesterday')
        if conflict:
            fields['note'] = '列表标注“昨天”；详情页显示“2026-09-08 19:04发布于广东”，与列表相对时间不一致。'
        for name in ('discovery-group_a.json', 'content-batch-01.json'):
            path = self.raw / DATE / 'raw' / name
            data = news.read(path)
            data['articles'][0].update(fields)
            publish.save(path, data)

    def test_yesterday_date_precision_survives_sorting_and_feed(self):
        self.set_manus_yesterday()
        result = self.process()
        self.assertEqual(len(result['items']), 1)
        manuscript = next(i for i in result['items'] if i['collector'] == 'manus')
        self.assertEqual(manuscript['publishedAt'], '2026-09-09')
        self.assertEqual(manuscript['publishedPrecision'], 'date')
        self.assertEqual(manuscript['timeEvidence']['originalText'], '昨天')
        self.assertEqual(result['items'][0]['collector'], 'manus')
        self.assertEqual(news.read(self.workspace / 'data/manus/current.json')['items'][0]['publishedAt'], '2026-09-09')
        # Sorting must not relax the original timestamp contract.
        with self.assertRaises(ValueError):
            snapshot.timestamp('2026-09-09')

    def test_conflicting_manus_time_is_isolated_before_aihot_deduplication(self):
        self.set_manus_yesterday(conflict=True, duplicate=True)
        result = self.process()
        self.assertEqual(result['items'], [])
        quarantine = result['collectionStatus']['quarantined']
        self.assertEqual(len(quarantine), 1)
        self.assertEqual(quarantine[0]['reasonCode'], 'original_publication_time_conflict')
        self.assertNotIn('note', quarantine[0])
        audit = next(a for a in result['collectionStatus']['sources'] if a['name'] == '游戏葡萄')
        self.assertEqual(audit['usableArticles'], 0)
        self.assertEqual(audit['status'], 'partial')
        evidence = news.read(self.workspace / 'inputs/publication-time-review.json')
        self.assertIn('2026-09-08 19:04发布', evidence[0]['note'])
        self.assertEqual(evidence[0]['published_at'], '2026-09-09')

    def test_all_sources_failed_blocks_publication(self):
        shutil.rmtree(self.raw)
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'failed'}}})
        with self.assertRaisesRegex(ValueError, 'All sources'):
            self.process()
        self.assertFalse((self.workspace / 'inputs/processed.json').exists())

    def test_aihot_only_is_rejected_before_any_model(self):
        with patch.object(news.screen_news, 'screen_items') as model:
            with self.assertRaisesRegex(ValueError, 'AIHOT fallback is disabled'):
                self.process(enabled=False)
        model.assert_not_called()

    def test_verified_zero_articles_is_not_failure(self):
        self.manus_sample([])
        result = self.process()
        self.assertEqual(result['items'], [])
        self.assertFalse(result['collectionStatus']['degraded'])

    def test_model_failure_blocks_even_with_successful_source(self):
        def failed(items, *args, **kwargs):
            return {}, {'irrelevant': 0}
        with self.assertRaisesRegex(ValueError, 'relevance'):
            news.process(DATE, self.workspace, self.raw, screen_fn=failed, enrich_fn=enrich)
        saved = news.read(self.workspace / 'inputs/article-library.json')
        self.assertEqual(saved['articleLibraryCount'], 1)
        self.assertEqual(saved['selectedArticles'], 0)
        self.assertEqual(saved['allArticles'][0]['garenaSelection']['status'], 'pending')
        self.assertNotIn('content_text', saved['allArticles'][0])

    def two_manus_candidates(self):
        (self.workspace / 'data/cache').mkdir(parents=True, exist_ok=True)
        other = {**self.item, 'id': 'second', 'title': '另一公司发布AI工具', 'url': 'https://example.com/second'}
        self.manus_sample([self.item, other])
        _, _, articles = news.load_manus(DATE, self.raw, self.groups)
        return news.candidates([], articles)

    def test_one_new_relevance_timeout_blocks_despite_one_cached_success(self):
        pool = self.two_manus_candidates()
        tx = news.tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        cache = self.workspace / 'data/cache/news_relevance.json'
        screen_news.screen_items(pool[:1], tx, cache, lambda *a, **k: json.dumps(
            {'relevant': True, 'reason': '具体AI事件', 'evidence': pool[0]['title']}))
        saved = news.read(cache)
        calls = []
        def timeout(*args, **kwargs):
            calls.append(1)
            raise TimeoutError('private response')
        def actual_screen(items, taxonomy, path, **kwargs):
            return screen_news.screen_items(items, taxonomy, path, llm_fn=timeout, **kwargs)
        with self.assertRaisesRegex(ValueError, 'no new model success'):
            news.process(DATE, self.workspace, self.raw, screen_fn=actual_screen, enrich_fn=enrich)
        self.assertEqual(len(calls), 1)
        self.assertEqual(news.read(cache), saved)
        self.assertFalse((self.workspace / 'inputs/processed.json').exists())
        self.assertEqual(news.read(self.workspace / 'inputs/model-failure.json')['modelSuccesses'], 0)

    def test_one_new_enrichment_timeout_blocks_despite_one_cached_success(self):
        pool = self.two_manus_candidates()
        tx = news.tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        cache = self.workspace / 'data/cache/news_enrichment.json'
        with patch.object(enrich_news, 'call_llm', return_value=json.dumps(
                {'category': 'general', 'tags': {}, 'summary': '公开信息描述产品功能。' * 12})):
            enrich_news.enrich_items(pool[:1], tx, str(cache))
        saved = news.read(cache)
        with patch.object(enrich_news, 'call_llm', side_effect=TimeoutError('private response')) as call:
            with self.assertRaisesRegex(ValueError, 'no new model success'):
                news.process(DATE, self.workspace, self.raw, screen_fn=screen)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(news.read(cache), saved)
        self.assertFalse((self.workspace / 'inputs/processed.json').exists())
        self.assertEqual(news.read(self.workspace / 'inputs/model-failure.json')['stage'], 'enrichment')
        review = news.read(self.workspace / 'inputs/enrichment-review.json')
        self.assertEqual(len(review), 2)
        self.assertTrue(any(r['result'].get('error', {}).get('category') == 'timeout' for r in review))
        self.assertNotIn('private response', json.dumps(review))
        library = news.read(self.workspace / 'inputs/article-library.json')
        self.assertEqual(library['articleLibraryCount'], 2)
        self.assertEqual(library['selectedArticles'], 1)
        self.assertEqual([i['garenaSelection']['status'] for i in library['allArticles']], ['selected', 'pending'])

    def test_content_only_failure_and_pure_cache_reuse_are_not_service_outages(self):
        pool = self.two_manus_candidates()
        tx = news.tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        cache = self.workspace / 'data/cache/news_relevance.json'
        screen_news.screen_items(pool[:1], tx, cache, lambda *a, **k: json.dumps(
            {'relevant': True, 'reason': '具体AI事件', 'evidence': pool[0]['title']}))
        def actual_screen(items, taxonomy, path, **kwargs):
            return screen_news.screen_items(items, taxonomy, path, llm_fn=lambda *a, **k: json.dumps(
                {'relevant': True, 'reason': '证据不合格', 'evidence': '输入中不存在的内容'}), **kwargs)
        result = news.process(DATE, self.workspace, self.raw, screen_fn=actual_screen, enrich_fn=enrich)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['collectionStatus']['quarantinedArticles'], 1)
        cached = {'status': 'complete', 'modelAttempted': False, 'cacheHit': True}
        succeeded = {'status': 'complete', 'modelAttempted': True, 'cacheHit': False}
        failed = {'status': 'failed', 'modelAttempted': True, 'error': {'category': 'timeout'}}
        self.assertIsNone(news.new_model_failure({'cached': cached}, 'status'))
        self.assertIsNone(news.new_model_failure({'success': succeeded, 'failed': failed}, 'status'))

    def test_failed_item_is_isolated_at_each_model_stage(self):
        second = {**self.item, 'id': 'second', 'title': '另一篇报道', 'url': 'https://example.com/second'}
        self.manus_sample([self.item, second])
        def partly_screen(items, *args, **kwargs):
            result, stats = screen(items, *args, **kwargs)
            result.pop(screen_news.item_key(items[1]))
            return result, stats
        def partly_enrich(items, *args):
            return enrich(items[:1])
        for screening, enriching, stage in [(partly_screen, enrich, 'relevance'), (screen, partly_enrich, 'enrichment')]:
            result = news.process(DATE, self.workspace, self.raw, screen_fn=screening, enrich_fn=enriching)
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(result['collectionStatus']['quarantinedArticles'], 1)
            self.assertEqual(result['collectionStatus']['quarantined'][0]['stage'], stage)
            evidence = news.read(self.workspace / 'inputs/company-evidence.json')
            self.assertEqual([i['id'] for i in evidence], [i['id'] for i in result['items']])
            self.assertEqual(len(result['allArticles']), 2)
            self.assertEqual([i['garenaSelection']['status'] for i in result['allArticles']], ['selected', 'pending'])

    def test_retired_aihot_input_is_not_read_even_with_wrong_window(self):
        publish.save(self.workspace / 'inputs/aihot.json', {'collectionWindow': {}, 'items': [self.item]})
        self.assertEqual(self.process()['items'][0]['collector'], 'manus')

    def test_aihot_timeline_keeps_slow_sources_and_obeys_batch_boundaries(self):
        window = ten_am_window(DATE)
        item = {**self.item, 'publishedAt': '2026-09-08T12:00:00+08:00',
                'discoveredAt': '2026-09-10T08:00:00+08:00'}
        self.assertTrue(aihot_in_window(window, item))
        self.assertFalse(aihot_in_window(window, {**item, 'discoveredAt': window['end']}))
        self.assertTrue(aihot_in_window(window, {**item, 'discoveredAt': window['start']}))
        self.assertFalse(aihot_in_window(window, {**item, 'publishedAt': '2026-09-01T12:00:00+08:00'}))
        self.assertTrue(aihot_in_window(window, {**item, 'publishedAt': None}))
        with patch.object(snapshot, 'fetch_items') as fetch, \
             patch.object(snapshot, 'fetch_latest_daily') as daily, \
             patch.object(snapshot, 'fetch_hot_topics') as hot:
            with self.assertRaisesRegex(ValueError, 'AIHOT collection is disabled'):
                news.collect(DATE, self.workspace / 'inputs/aihot.json')
        fetch.assert_not_called()
        daily.assert_not_called()
        hot.assert_not_called()

    def test_failed_summary_never_publishes_fallback(self):
        with self.assertRaisesRegex(ValueError, 'summary/classification'):
            news.process(DATE, self.workspace, self.raw, screen_fn=screen, enrich_fn=lambda *args: {})

    def test_missing_body_marks_only_that_source_partial(self):
        self.manus_sample()
        (self.raw / DATE / 'raw/content-batch-01.json').unlink()
        result = self.process()
        self.assertEqual(result['items'], [])
        audit = next(a for a in result['collectionStatus']['sources'] if a['name'] == '游戏葡萄')
        self.assertEqual(audit['status'], 'partial')
        self.assertEqual(audit['usableArticles'], 0)
        self.assertEqual(audit['articleLibraryCount'], 1)
        self.assertEqual(len(result['allArticles']), 1)
        self.assertEqual(len(result['allArticles'][0]['sourceRefs']), 1)
        self.assertTrue(result['allArticles'][0]['metadataOnly'])

    def test_relevance_exclusion_stays_in_library_with_real_screen_keys(self):
        pool = self.two_manus_candidates()
        def excluding(items, *args, **kwargs):
            result, stats = screen(items)
            result[screen_news.item_key(items[0])].update(reason='AI 公司融资')
            result[screen_news.item_key(items[1])].update(relevant=False, reason='普通游戏新闻')
            # Conservation derives from decisions, not potentially stale counters.
            return result, stats
        result = news.process(DATE, self.workspace, self.raw, screen_fn=excluding, enrich_fn=enrich)
        self.assertEqual([r['id'] for r in result['allArticles']], [i['id'] for i in pool])
        self.assertEqual([r['garenaSelection']['status'] for r in result['allArticles']], ['selected', 'not_selected'])
        self.assertEqual([r['garenaSelection']['reason'] for r in result['allArticles']], ['AI 公司融资', '普通游戏新闻'])
        self.assertTrue(result['allArticles'][1]['summary'])
        self.assertEqual(result['allArticles'][1]['classificationStatus'], 'complete')
        self.assertEqual(result['allArticles'][1]['classification']['tags'], {})
        stats = result['collectionStatus']
        self.assertEqual((stats['candidateArticles'], stats['selectedArticles'], stats['excludedArticles'], stats['quarantinedArticles']), (2, 1, 1, 0))
        self.assertEqual(stats['publishedArticles'], stats['selectedArticles'])
        self.assertEqual(stats['articleLibraryCount'], 2)
        self.assertEqual(result['selectedArticles'], 1)
        self.assertEqual([r['id'] for r in news.read(self.workspace / 'inputs/company-evidence.json')], [pool[0]['id']])

    def test_metadata_only_discovery_survives_without_any_model_request(self):
        self.manus_sample()
        (self.raw / DATE / 'raw/content-batch-01.json').unlink()
        # The sole available source has verified metadata but no usable body.
        # Empty successful sources must not accidentally make this test pass.
        for group in self.groups:
            path = self.raw / DATE / 'raw' / f'discovery-{group}.json'
            if group != 'group_a':
                path.unlink()
            else:
                data = news.read(path)
                for audit in data['source_audits'][1:]:
                    audit.update(source_status='failed', note='unavailable')
                publish.save(path, data)
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'failed'}}})
        with patch.object(news.screen_news, 'screen_items', side_effect=AssertionError('model forbidden')) as scr, \
             patch.object(news.enrich_news, 'enrich_items', side_effect=AssertionError('model forbidden')) as enr:
            result = news.process(DATE, self.workspace, self.raw)
        scr.assert_not_called()
        enr.assert_not_called()
        self.assertEqual(result['items'], [])
        self.assertEqual(len(result['allArticles']), 1)
        row = result['allArticles'][0]
        self.assertTrue(row['metadataOnly'])
        self.assertEqual(row['summary'], '')
        self.assertEqual(row['garenaSelection']['status'], 'pending')
        self.assertNotIn('classification', row)
        self.assertNotIn('content_text', row)
        self.assertEqual(result['collectionStatus']['quarantinedArticles'], 1)
        self.assertEqual(result['collectionStatus']['quarantined'][0]['stage'], 'content')
        self.assertEqual(result['collectionStatus']['candidateArticles'], 1)
        self.assertEqual(news.read(self.workspace / 'inputs/company-evidence.json'), [])
        self.assertEqual(news.read(self.workspace / 'data/manus/current.json')['items'], [])

    def test_wrong_body_title_becomes_metadata_only_without_model_request(self):
        self.manus_sample()
        path = self.raw / DATE / 'raw/content-batch-01.json'
        data = news.read(path)
        data['articles'][0]['title'] = '完全不同的另一篇正文'
        publish.save(path, data)
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'failed'}}})
        def forbidden(*args, **kwargs):
            self.fail('Unvalidated body reached model')
        result = news.process(DATE, self.workspace, self.raw, screen_fn=forbidden, enrich_fn=forbidden)
        self.assertEqual(len(result['allArticles']), 1)
        self.assertTrue(result['allArticles'][0]['metadataOnly'])

    def test_invalid_discovery_identity_or_time_never_enters_library(self):
        for update in ({'source_home_url': 'https://unverified.example'}, {'source_platform': 'Unverified'},
                       {'published_at': '2026-09-08T08:00:00+08:00', 'published_date': '2026-09-08'}):
            with self.subTest(update=update):
                self.manus_sample()
                path = self.raw / DATE / 'raw/discovery-group_a.json'
                data = news.read(path)
                data['articles'][0].update(update)
                publish.save(path, data)
                publish.save(self.workspace / 'inputs/aihot.json', {'collectionWindow': ten_am_window(DATE), 'items': []})
                result = self.process()
                self.assertEqual(result['allArticles'], [])
                self.assertEqual(result['items'], [])

    def test_conflicting_time_without_body_is_not_a_metadata_library_backdoor(self):
        self.set_manus_yesterday(conflict=True)
        (self.raw / DATE / 'raw/content-batch-01.json').unlink()
        result = self.process()
        self.assertEqual(result['allArticles'], [])
        self.assertEqual(result['collectionStatus']['quarantinedArticles'], 1)
        self.assertEqual(result['collectionStatus']['quarantined'][0]['stage'], 'publication_time')
        self.assertEqual(result['collectionStatus']['candidateArticles'], 1)

    def test_body_only_timestamp_conflict_retains_private_original_evidence(self):
        self.set_manus_yesterday()
        path = self.raw / DATE / 'raw/content-batch-01.json'
        data = news.read(path)
        data['articles'][0]['note'] = '列表标注昨天；详情页显示2026-09-08 19:04发布，与列表相对时间不一致。'
        publish.save(path, data)
        result = self.process()
        self.assertEqual(result['allArticles'], [])
        evidence = news.read(self.workspace / 'inputs/publication-time-review.json')
        self.assertIn('2026-09-08 19:04发布', evidence[0]['note'])

    def test_all_excluded_articles_are_classified_without_entering_selection(self):
        def excluded(items, *args, **kwargs):
            return ({screen_news.item_key(i): {'status': 'complete', 'relevant': False,
                'reason': '无具体 AI 事件'} for i in items}, {'irrelevant': len(items)})
        calls = []
        def classify(items, tx, path):
            calls.append((len(items), tx['enrich'].get('article_scope')))
            return enrich(items, tx, path)
        result = news.process(DATE, self.workspace, self.raw, screen_fn=excluded, enrich_fn=classify)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['allArticles'][0]['garenaSelection']['status'], 'not_selected')
        self.assertEqual(result['allArticles'][0]['classification']['category'], 'general')
        self.assertEqual(result['allArticles'][0]['classificationStatus'], 'complete')
        self.assertEqual(calls, [(1, 'all_articles')])
        self.assertEqual(news.read(self.workspace / 'inputs/company-evidence.json'), [])
        self.assertEqual(result['collectionStatus']['excludedArticles'], 1)
        self.assertEqual(result['collectionStatus']['quarantinedArticles'], 0)

    def test_nonselected_success_cannot_mask_selected_model_failure(self):
        self.manus_sample([self.item, {**self.item, 'title': '普通家电行业评论', 'url': 'https://example.com/home'}])
        def mixed_screen(items, *args, **kwargs):
            return ({screen_news.item_key(i): {'status': 'complete', 'relevant': 'AI' in i['title']}
                     for i in items}, {'irrelevant': 1})
        calls = []
        def fail_selected(items, tx, path):
            calls.append(tx['enrich'].get('article_scope', 'selection'))
            if tx['enrich'].get('article_scope') == 'all_articles':
                return enrich(items, tx, path)
            return {enrich_news.enrich_item_key(i): {'enrichmentStatus': 'failed', 'modelAttempted': True,
                    'error': {'category': 'timeout'}} for i in items}
        with self.assertRaisesRegex(ValueError, 'no new model success'):
            news.process(DATE, self.workspace, self.raw, screen_fn=mixed_screen, enrich_fn=fail_selected)
        self.assertEqual(calls, ['selection'])
        library = news.read(self.workspace / 'inputs/article-library.json')['allArticles']
        self.assertEqual(len(library), 2)
        self.assertFalse((self.workspace / 'inputs/processed.json').exists())

    def test_all_local_content_failures_can_publish_library_without_selections(self):
        for stage, category in [('relevance', 'content'), ('relevance', 'output_limit'),
                                ('enrichment', 'content'), ('enrichment', 'output_limit')]:
            with self.subTest(stage=stage, category=category):
                def failed_screen(items, *args, **kwargs):
                    return ({screen_news.item_key(i): {'status': 'failed', 'modelAttempted': True,
                        'error': {'category': category}} for i in items}, {'irrelevant': 0})
                def failed_enrich(items, *args):
                    return {enrich_news.enrich_item_key(i): {'enrichmentStatus': 'failed',
                        'modelAttempted': True, 'error': {'category': category}} for i in items}
                result = news.process(DATE, self.workspace, self.raw,
                    screen_fn=failed_screen if stage == 'relevance' else screen,
                    enrich_fn=failed_enrich if stage == 'enrichment' else enrich)
                self.assertEqual(result['items'], [])
                self.assertEqual(result['articleLibraryCount'], 1)
                self.assertEqual(result['allArticles'][0]['garenaSelection']['status'], 'pending')
                self.assertEqual(result['collectionStatus']['quarantinedArticles'], 1)

    def test_partial_source_articles_reach_shared_news_pool(self):
        self.manus_sample()
        path = self.raw / DATE / 'raw/discovery-group_a.json'
        data = news.read(path)
        audit = next(a for a in data['source_audits'] if a['account_name'] == '游戏葡萄')
        audit.update(source_status='partial', note='boundary_unverified')
        publish.save(path, data)
        publish.save(self.workspace.parent / 'state.json', {'stages': {'aihot': {'status': 'failed'}}})
        result = self.process()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['collector'], 'manus')
        self.assertTrue(result['collectionStatus']['degraded'])

    def test_daily_company_inputs_do_not_reintroduce_weekly_exclusions(self):
        from company_index.inputs import load_articles
        current = {'id': 'aihot:new', 'title': '已筛选文章', 'url': 'https://example.com/new'}
        old = {'id': 'aihot:old', 'title': '历史文章', 'url': 'https://example.com/old'}
        publish.save(self.workspace / 'snapshot.json', {'collectionStatus': {'degraded': False},
            'all': {'items': [current]}, 'weekly': {'sections': [{'items': [old]}]}})
        rows = load_articles(self.workspace / 'snapshot.json', self.workspace / 'missing.json', self.raw, {})
        self.assertEqual([r['id'] for r in rows], ['aihot:new'])

    def test_manus_failure_still_attempts_script_content_and_news_without_aihot(self):
        (self.root / 'config').mkdir()
        for name in ('taxonomy.json', 'manus_sources.json'):
            shutil.copy(ROOT / 'config' / name, self.root / 'config' / name)
        calls = []
        def execute(cmd):
            if cmd[1].endswith('runner.py'):
                calls.append('discovery')
                return 1
            if 'collect' in cmd:
                self.fail('AIHOT must never be collected')
            calls.append('news' if 'process' in cmd else Path(cmd[1]).stem)
            return 0
        with contextlib.redirect_stdout(io.StringIO()):
            code = runner.run(self.root, DATE, list(runner.COMBINED_STAGES), combined=True,
                              ten_am=True, no_promote=True, execute=execute, source_mode='manus-only')
        self.assertEqual(code, 0)
        self.assertEqual(calls[:2], ['discovery', 'content_phase'])
        self.assertIn('news', calls)

    def test_snapshot_reads_prepared_pool_without_network_or_old_manus(self):
        # Approved Manus articles survive local rendering/frozen archives;
        # stale upstream inputs and daily reports are never read as fallback.
        publish.save(self.workspace / 'archive/2026-09-10.json',
                     {'date': '2026-09-10', 'finalized': True, 'items': []})
        publish.save(self.workspace / 'snapshot.json', {'dailyReports': {'2026-09-09': {'secret': 'old'}}})
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
        self.assertEqual(actual['all']['items'][0]['id'], result['items'][0]['id'])
        self.assertEqual(actual['dailyReports'], {})
        self.assertEqual(actual['hot'], {})
        self.assertEqual(actual['daily']['total'], 1)
        self.assertEqual(news.read(self.workspace / 'archive/2026-09-10.json')['items'][0]['id'], result['items'][0]['id'])
        publish.save(self.workspace / 'web/public/snapshot.json', actual)
        runner.validate_candidates(self.workspace, ROOT, ['news', 'snapshot'])
        actual['all']['items'] = []
        publish.save(self.workspace / 'web/public/snapshot.json', actual)
        with self.assertRaisesRegex(ValueError, '新闻与网页批次不一致'):
            runner.validate_candidates(self.workspace, ROOT, ['news', 'snapshot'])

    def test_retry_collector_invalidates_successful_downstream(self):
        calls = []
        def execute(cmd):
            stage = 'aihot' if 'collect' in cmd else 'news' if 'process' in cmd else Path(cmd[1]).stem
            calls.append(stage)
            return 1 if stage == 'runner' else 0
        with contextlib.redirect_stdout(io.StringIO()):
            for resume in (False, True):
                self.assertEqual(runner.run(self.root, DATE, list(runner.COMBINED_STAGES),
                    combined=True, ten_am=True, no_promote=True, resume=resume, execute=execute,
                    source_mode='manus-only'), 0)
        self.assertEqual(calls.count('aihot'), 0)
        self.assertEqual(calls.count('news'), 2)
        self.assertEqual(calls.count('build_company_overview'), 2)

    def test_failed_discovery_does_not_launch_paid_content(self):
        calls = []
        def execute(cmd):
            calls.append(Path(cmd[1]).stem)
            self.assertEqual(os.environ['MANUS_CONTENT_MODE'], 'script')
            return 1 if cmd[1].endswith('runner.py') else 0
        with patch.dict(os.environ, {'MANUS_CONTENT_MODE': 'manus'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run(self.root, DATE, list(runner.COMBINED_STAGES),
                combined=True, ten_am=True, no_promote=True, execute=execute, source_mode='manus-only'), 0)
        self.assertIn('content_phase', calls)


if __name__ == '__main__':
    unittest.main()
