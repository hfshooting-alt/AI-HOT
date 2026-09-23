"""Offline regressions for body classification independent from investment selection."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import enrich_news as enrich
import news_editorial_reviews as editorial
import tag_news
from news_selection import build_public_article_library


class ArticleProcessing(unittest.TestCase):
    def setUp(self):
        self.tx = tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        self.tx['model']['model'] = 'offline-test'
        self.tx.setdefault('enrich', {}).update(concurrency=1, max_new_items_per_run=10)
        self.library_tx = copy.deepcopy(self.tx)
        self.library_tx['enrich']['article_scope'] = 'all_articles'
        self.item = {'id': 'manus:example', 'title': '家电公司获得新融资', 'mpName': '测试媒体',
                     'url': 'https://example.com/article', 'publishedAt': '2026-09-22T09:00:00+08:00',
                     'collector': 'manus', 'content_text': '家电公司完成融资，资金用于生产线建设。' * 12}
        self.raw = {'summary': '家电公司完成融资，资金用于生产线建设。' * 5,
                    'category': 'financing', 'tags': {'industry': 'ai_other'}}

    def run_one(self, raw, tx=None):
        with patch.object(enrich, 'call_llm', return_value=json.dumps(raw, ensure_ascii=False)) as call:
            result = enrich.enrich_one(tx or self.library_tx, self.item)
        return result, call

    def test_general_articles_never_receive_a_fabricated_ai_dimension(self):
        result, call = self.run_one(self.raw)
        self.assertEqual(result['classification']['category'], 'financing')
        self.assertEqual(result['classification']['tags'], {})
        self.assertEqual(result['enrichmentStatus'], 'complete')
        self.assertIn('任何行业', call.call_args.args[1])
        self.assertNotIn('围绕有正文依据的 AI 主线', call.call_args.args[1])
        selected_system, _ = enrich.build_enrich_prompt(self.tx, 'title', 'source', 'body')
        self.assertIn('围绕有正文依据的 AI 主线', selected_system)

    def test_legacy_success_is_reused_at_its_real_key_without_creating_new_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            legacy = {'summary': self.raw['summary'], 'classification': tag_news.validate(self.tx, self.raw),
                      'enrichmentStatus': 'complete'}
            key = enrich.enrich_cache_key(self.tx, self.item)
            sha = hashlib.sha256(self.item['content_text'].encode()).hexdigest()[:16]
            self.assertEqual(key, f'{tag_news.cache_prefix(self.tx)}:enrich-v4:{enrich.enrich_item_key(self.item)}:{sha}')
            tag_news.save_cache(path, {key: legacy})
            before = path.read_bytes()
            with patch.object(enrich, 'call_llm', side_effect=AssertionError('No new request')):
                results = enrich.enrich_items([self.item], self.library_tx, str(path))
            row = results[enrich.enrich_item_key(self.item)]
            self.assertTrue(row['cacheHit'])
            self.assertEqual(row['processingCacheKey'], key)
            self.assertEqual(row['processingPrompt'], 'selected-v4')
            self.assertEqual(path.read_bytes(), before)
            public = build_public_article_library([self.item], [], {self.item['id']: {
                'status': 'complete', 'relevant': False}}, {self.item['id']: row})[0]
            self.assertEqual(public['classification']['tags'], {})
            self.assertEqual(public['garenaSelection']['status'], 'not_selected')

    def test_raw_response_is_private_even_on_success_and_never_saved_in_cache(self):
        raw = {**self.raw, 'private_marker': 'PRIVATE_RAW_VALUE'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            with patch.object(enrich, 'call_llm', return_value=json.dumps(raw)):
                result = enrich.enrich_items([self.item], self.library_tx, str(path))[enrich.enrich_item_key(self.item)]
            self.assertIn('PRIVATE_RAW_VALUE', result['privateReview']['modelResponse'])
            self.assertNotIn('PRIVATE_RAW_VALUE', path.read_text(encoding='utf-8'))
            self.assertNotIn('privateReview', path.read_text(encoding='utf-8'))
            public = build_public_article_library([self.item], [], enrichments={self.item['id']: result})[0]
            self.assertNotIn('PRIVATE_RAW_VALUE', json.dumps(public))
            self.assertNotIn('processingCacheKey', public)

    def test_reviewed_summary_projection_runs_after_cache_save_on_fresh_and_cached_results(self):
        reviewed = '经原文核对，该家电公司介绍了生产线建设安排和产品销售情况，披露本轮融资计划。报道区分了既有业务与此次新增进展，没有将历史数字写成今天的新事实。'
        digest = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
        rules = [{'articleId': self.item['id'], 'title': self.item['title'], 'url': self.item['url'],
                  'contentSha256': digest(self.item['content_text']), 'fromSummarySha256': digest(self.raw['summary']),
                  'toSummary': reviewed, 'reviewedAt': '2026-09-23T11:00:00+08:00', 'reason': '原文校正'}]
        apply = editorial.apply_summary_review
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            key = enrich.enrich_cache_key(self.library_tx, self.item)

            def projection(item, result):
                self.assertEqual(tag_news.load_cache(path)[key]['summary'], self.raw['summary'])
                return apply(item, result, rules)

            with patch.object(editorial, 'apply_summary_review', side_effect=projection), \
                 patch.object(enrich, 'call_llm', return_value=json.dumps(self.raw)) as call:
                first = enrich.enrich_items([self.item], self.library_tx, str(path))[enrich.enrich_item_key(self.item)]
                before = path.read_bytes()
                second = enrich.enrich_items([self.item], self.library_tx, str(path))[enrich.enrich_item_key(self.item)]
            self.assertEqual(call.call_count, 1)
            self.assertEqual(first['summary'], reviewed)
            self.assertEqual(second['summary'], reviewed)
            self.assertEqual(second['summaryOrigin'], 'editorial_review')
            self.assertEqual(json.loads(first['privateReview']['modelResponse'])['summary'], self.raw['summary'])
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn('editorialReview', tag_news.load_cache(path)[key])

    def test_release_quote_failures_are_specific_local_and_never_retried(self):
        for quote, reason in [(None, 'missing'), (7, 'not_string'), ('短', 'too_short'), ('原文没有的发布句子', 'not_in_source')]:
            with self.subTest(reason=reason):
                tx = copy.deepcopy(self.tx)
                tx['enrich']['max_attempts'] = 2
                raw = {**self.raw, 'category': 'release', 'release_evidence': quote}
                result, call = self.run_one(raw, tx)
                self.assertEqual(call.call_count, 1)
                self.assertEqual(result['privateReview']['validationReason'], 'release_evidence_' + reason)
                self.assertEqual(json.loads(result['privateReview']['modelResponse']), raw)
                self.assertEqual(result['error']['category'], 'content')
                self.assertEqual(result['classificationStatus'], 'failed')

    def test_release_quote_allows_only_contiguous_unicode_whitespace_differences(self):
        content = '公司宣布新产品上线不过数天，\n\u3000全球用户已开始使用该项目\u00a0。'
        self.assertEqual(enrich.release_evidence_match('新产品上线不过数天', content), 'exact')
        self.assertEqual(enrich.release_evidence_match('新产品上线不过数天，全球用户已开始使用该项目。', content),
                         'whitespace_normalized')
        for bad in ('新产品上线不过数月，全球用户已开始使用该项目。',
                    '新产品上线不过数天，全球用户使用该项目。',
                    '新产品上线不过数天全球用户已开始使用该项目。',
                    '全球用户已开始使用该项目。新产品上线不过数天，', '   \u3000'):
            with self.subTest(quote=bad):
                self.assertIsNone(enrich.release_evidence_match(bad, content))

    def test_normalized_quote_records_private_match_without_changing_raw_response(self):
        self.item['content_text'] = '公司宣布全新产品上线不过数天，\n 全球用户开始使用该项目 。' * 4
        raw = {**self.raw, 'category': 'release', 'release_evidence': '全新产品上线不过数天，全球用户开始使用该项目。'}
        result, call = self.run_one(raw, self.tx)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['enrichmentStatus'], 'complete')
        self.assertEqual(result['privateReview']['evidenceMatch'], 'whitespace_normalized')
        self.assertEqual(json.loads(result['privateReview']['modelResponse']), raw)
        self.assertNotIn('privateReview', enrich.cache_result(result))

    def test_sales_milestone_projects_general_but_new_launch_keeps_release(self):
        self.item['title'] = '《盛世天下》系列官宣销量突破600万套，再次刷新全球纪录'
        self.item['content_text'] = '该游戏女帝篇上线21天后，系列累计销量突破600万套。' * 4
        raw = {**self.raw, 'category': 'release', 'release_evidence': '该游戏女帝篇上线21天后'}
        result, _ = self.run_one(raw)
        self.assertEqual(result['classification']['category'], 'general')
        self.assertEqual(result['classification']['tags'], {})
        self.assertEqual(result['privateReview']['classificationBoundary']['reason'], 'sales_milestone_not_release')
        self.assertEqual(json.loads(result['privateReview']['modelResponse'])['category'], 'release')
        for title in ('《新作》正式发布，销量突破600万套', '销量突破600万套，新版本正式上线',
                      '新游发售首日，销量突破100万套', '销量突破600万套，推出重大版本',
                      '销量突破600万套，DLC今日发布'):
            with self.subTest(title=title):
                self.item['title'] = title
                result, _ = self.run_one(raw)
                self.assertEqual(result['classification']['category'], 'release')
                self.assertNotIn('classificationBoundary', result['privateReview'])

    def test_milestone_cache_projection_keeps_original_cache_bytes(self):
        self.item['title'] = '《盛世天下》系列官宣销量突破600万套，再次刷新全球纪录'
        original = {'summary': self.raw['summary'], 'classification': {'category': 'release', 'tags': {},
                    'autoFallback': False, 'autoFilled': []}, 'enrichmentStatus': 'complete'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            key = enrich.enrich_cache_key(self.library_tx, self.item)
            tag_news.save_cache(path, {key: original})
            before = path.read_bytes()
            with patch.object(enrich, 'call_llm', side_effect=AssertionError('No request')):
                result = enrich.enrich_items([self.item], self.library_tx, str(path))[enrich.enrich_item_key(self.item)]
            self.assertEqual(result['classification']['category'], 'general')
            self.assertEqual(result['classification']['tags'], {})
            self.assertEqual(result['privateReview']['classificationBoundary']['reason'], 'sales_milestone_not_release')
            self.assertEqual(result['processingCacheKey'], key)
            self.assertTrue(result['cacheHit'])
            self.assertFalse(result['modelAttempted'])
            self.assertEqual(path.read_bytes(), before)

    def test_valid_classification_survives_unrecoverable_summary_and_replays_without_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            with patch.object(enrich, 'call_llm', return_value=json.dumps({**self.raw, 'summary': ''})), \
                 patch.object(enrich, 'deterministic_summary', return_value=''):
                result = enrich.enrich_items([self.item], self.library_tx, str(path))[enrich.enrich_item_key(self.item)]
            self.assertEqual(result['enrichmentStatus'], 'partial')
            self.assertEqual(result['summaryStatus'], 'failed')
            with patch.object(enrich, 'call_llm', side_effect=AssertionError('No automatic retry')):
                replay = enrich.enrich_items([self.item], self.library_tx, str(path))[enrich.enrich_item_key(self.item)]
            public = build_public_article_library([self.item], [], enrichments={self.item['id']: replay})[0]
            self.assertEqual(public['classificationStatus'], 'complete')
            self.assertEqual(public['summaryStatus'], 'failed')
            self.assertEqual(public['garenaSelection']['status'], 'pending')

    def test_metadata_only_cannot_be_classified_by_a_supplied_result(self):
        result, _ = self.run_one(self.raw)
        public = build_public_article_library([{**self.item, 'metadataOnly': True}], [],
                                             enrichments={self.item['id']: result})[0]
        self.assertEqual(public['contentStatus'], 'awaiting_body')
        self.assertEqual(public['classificationStatus'], 'pending')
        self.assertEqual(public['summaryStatus'], 'pending')
        self.assertNotIn('classification', public)
        self.assertEqual(public['summary'], '')


if __name__ == '__main__':
    unittest.main()
