"""Direct-news regression: exact release evidence, without provider requests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import enrich_news


FIRST = '甲公司发布新一代模型，使用成本较前代降低约40%。'
SECOND = '乙公司同日推出两款低价模型。'
CONTENT = FIRST + '\n产品说明详细列出了输入与输出定价，并介绍不同场景下的测试方法和适用范围。\n' + SECOND
SUMMARY = ('甲公司发布新一代模型，并披露成本较前代降低约40%；乙公司同日推出两款低价模型。'
           '文章列出了输入与输出定价，介绍了不同场景下的测试方法和适用范围，主要事件是两家公司的模型发布。')


class DirectEditorialEvidenceTests(unittest.TestCase):
    def tax(self, library):
        # Read public taxonomy only: do not load .env or resolve a live model.
        tx = json.loads((ROOT / 'config/taxonomy.json').read_text('utf-8'))
        tx.setdefault('llm', {})['model'] = 'offline-direct-editorial'
        if library:
            tx.setdefault('enrich', {})['article_scope'] = 'all_articles'
        return tx

    def evaluate(self, library, quote):
        tx = self.tax(library)
        item = {'id': 'direct:offline', 'title': '两家公司同日发布低价模型',
                'mpName': '离线来源', 'content_text': CONTENT}
        before = copy.deepcopy(item)
        payload = {'summary': SUMMARY, 'category': 'release',
                   'tags': {'industry': 'ai_model', 'issuer': 'bigcorp'},
                   'release_evidence': quote}
        response = json.dumps(payload, ensure_ascii=False)
        with patch.object(enrich_news, 'call_llm', return_value=response) as mocked:
            result = enrich_news.enrich_one(tx, item)
        mocked.assert_called_once()  # A content rejection must not cause a retry.
        self.assertEqual(item, before)
        self.assertEqual(result['privateReview']['modelResponse'], response)
        system = mocked.call_args.args[1]
        self.assertIn('一段连续原话', system)
        self.assertIn('替换标点', system)
        return result

    def test_one_exact_passage_is_enough_for_multiple_release_events(self):
        for library in (False, True):
            with self.subTest(library=library):
                result = self.evaluate(library, FIRST)
                self.assertEqual(result['enrichmentStatus'], 'complete')
                self.assertEqual(result['classification']['category'], 'release')
                self.assertEqual(result['privateReview']['evidenceMatch'], 'exact')
                self.assertEqual(result['summary'], SUMMARY)
                if library:
                    self.assertEqual(result['classification']['tags'], {})

    def test_true_fragments_cannot_be_spliced_or_repunctuated(self):
        self.assertIn(FIRST, CONTENT)
        self.assertIn(SECOND, CONTENT)
        invalid_quotes = (FIRST + SECOND, FIRST.replace('，', '；'))
        for library in (False, True):
            for quote in invalid_quotes:
                with self.subTest(library=library, quote=quote):
                    result = self.evaluate(library, quote)
                    self.assertEqual(result['classificationStatus'], 'failed')
                    self.assertEqual(result['enrichmentStatus'], 'fallback')
                    self.assertEqual(result['privateReview']['validationReason'], 'release_evidence_not_in_source')
                    self.assertEqual(result['privateReview']['evidenceMatch'], 'not_found')
                    self.assertEqual(result['error']['category'], 'content')
                    self.assertFalse(result['error']['systemic'])

    def test_known_boundaries_project_fresh_and_cached_without_cache_write(self):
        cases = (('甲公司发布模型 | 极客早知道', 'roundup_not_release'),
                 ('华尔街见闻早餐FM-Radio | 2026年9月23日', 'roundup_not_release'),
                 ('报道：苹果开发新型健身追踪器原型机，目标直指Whoop', 'prototype_not_release'))
        for library in (False, True):
            tx = self.tax(library)
            for title, reason in cases:
                with self.subTest(library=library, title=title):
                    item = {'id': 'direct:offline-roundup', 'title': title,
                            'mpName': '离线来源', 'content_text': CONTENT}
                    raw = json.dumps({'summary': SUMMARY, 'category': 'release',
                        'tags': {'industry': 'ai_model', 'issuer': 'bigcorp'},
                        'release_evidence': FIRST}, ensure_ascii=False)
                    with patch.object(enrich_news, 'call_llm', return_value=raw) as mocked:
                        fresh = enrich_news.enrich_one(tx, item)
                    mocked.assert_called_once()
                    self.assertEqual(fresh['classification']['category'], 'general')
                    self.assertEqual(fresh['classification']['tags'], {})
                    self.assertEqual(fresh['privateReview']['modelResponse'], raw)
                    self.assertEqual(fresh['privateReview']['classificationBoundary']['reason'], reason)
                    # A saved successful response remains a release in storage;
                    # only the returned publication projection is corrected.
                    saved = {**fresh, 'classification': {'category': 'release',
                        'tags': {'industry': 'ai_model', 'issuer': 'bigcorp'},
                        'autoFallback': False, 'autoFilled': []}}
                    saved.pop('privateReview')
                    with tempfile.TemporaryDirectory() as directory, patch.object(enrich_news.tag_news, 'cache_prefix', return_value='offline-roundup'):
                        cache_path = Path(directory) / 'cache.json'
                        cache_key = enrich_news.enrich_cache_key(tx, item)
                        cache_path.write_text(json.dumps({cache_key: saved}, ensure_ascii=False), 'utf-8')
                        before = cache_path.read_bytes()
                        with patch.object(enrich_news, 'call_llm', side_effect=AssertionError('cache must prevent new calls')):
                            result = enrich_news.enrich_items([item], tx, str(cache_path))[enrich_news.enrich_item_key(item)]
                        self.assertEqual(cache_path.read_bytes(), before)
                    self.assertFalse(result['modelAttempted'])
                    self.assertTrue(result['cacheHit'])
                    self.assertEqual(result['classification']['category'], 'general')
                    self.assertEqual(result['privateReview']['classificationBoundary']['reason'], reason)

    def test_prototype_development_boundary_preserves_releases_and_other_categories(self):
        for title in ('公司正式发布自主研发的机器人原型', '公司研发的原型机现已上线',
                      '公司已发布新研发的追踪器原型机', '公司发布自主研发的机器人原型机',
                      '公司正在研发的新型原型机现已开售',
                      '公司研发的原型机取得测试进展'):
            self.assertIsNone(enrich_news.event_boundary_reason('release', title))
        # Mixed/future launch titles need source-body evidence; do not decide
        # them with a broad title regex that can override genuine releases.
        self.assertIsNone(enrich_news.event_boundary_reason('release', '公司正在研发原型机，计划2028年正式推出'))
        self.assertEqual(enrich_news.event_boundary_reason('release', '公司正在研发追踪器原型机'),
                         'prototype_not_release')
        self.assertIsNone(enrich_news.event_boundary_reason('paper', '公司正在开发原型机'))

    def test_roundup_boundary_does_not_match_generic_morning_or_similar_names(self):
        for title in ('公司今早发布新模型', '早餐机器人正式发布', '极客早知道模型正式发布',
                      '新模型发布 | 极客早知道更多', '华尔街见闻早餐FM推出新应用'):
            self.assertIsNone(enrich_news.event_boundary_reason('release', title))
        self.assertIsNone(enrich_news.event_boundary_reason('paper', '研究进展 | 极客早知道'))


if __name__ == '__main__':
    unittest.main()
