"""Exact article-bound review replay; no model call or cache mutation."""
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
from apply_quality_review import apply_article_value_reviews
from company_index.extraction import normalize_company
import funding_table

TX = json.loads((ROOT / 'config/taxonomy.json').read_text(encoding='utf-8'))


class ArticleExtractionReviewTests(unittest.TestCase):
    def setUp(self):
        self.article = {'id': 'reviewed-article', 'title': 'Example product',
            'url': 'https://example.test/article', 'content_text': 'Example公司发布Alpha工具。',
            'publishedAt': '2026-09-22T08:00:00+08:00', 'mpName': 'Source'}
        self.company = normalize_company({'company_name': 'Example', 'entity_type': 'company',
            'products': [{'name': 'Alpha', 'relationship': 'owned', 'quote': 'Example公司发布Alpha工具。'}],
            'business': '工具开发', 'industry_id': 'ai_other'}, TX)
        self.decision = {k: self.article[v] for k, v in
                         [('articleId', 'id'), ('title', 'title'), ('url', 'url')]}
        self.decision.update(contentSha256=hashlib.sha256(self.article['content_text'].encode()).hexdigest(),
            reviewedAt='2026-09-22T12:00:00+08:00', reason='原文完整审校，排除仅履历提及的主体',
            companies=[self.company])
        self.rules = {'articleExtractionReviews': [self.decision]}
        self.extracts = {self.article['id']: {'status': 'complete', 'modelAttempted': False,
            'cacheHit': True, 'modelCalls': 0, 'companies': [dict(self.company, company_name='CareerOnly')]}}

    def apply(self, articles=None, extracts=None, rules=None, **kwargs):
        return apply_article_value_reviews(articles or [self.article],
            self.extracts if extracts is None else extracts, self.rules if rules is None else rules, **kwargs)

    def test_exact_binding_replays_deep_copy_without_changing_cache_or_statistics(self):
        raw_before, rules_before = copy.deepcopy(self.extracts), copy.deepcopy(self.rules)
        result = self.apply()
        row = result[self.article['id']]
        self.assertEqual(row['companies'], [self.company])
        self.assertEqual({k: v for k, v in row.items() if k not in ('companies', 'articleExtractionReview')},
                         {k: v for k, v in raw_before[self.article['id']].items() if k != 'companies'})
        self.assertEqual(self.apply(extracts=result), result)
        self.assertEqual(self.extracts, raw_before)
        self.assertEqual(self.rules, rules_before)
        row['companies'][0]['products'][0]['name'] = 'changed output copy'
        self.assertEqual(self.rules, rules_before)
        self.assertEqual(self.extracts, raw_before)

    def test_id_title_url_and_exact_body_changes_do_not_apply(self):
        for field, value in [('id', 'different'), ('title', 'Example product '),
                ('url', 'https://example.test/other'), ('content_text', self.article['content_text'] + '\n')]:
            with self.subTest(field=field):
                article = {**self.article, field: value}
                extracts = {article['id']: copy.deepcopy(self.extracts[self.article['id']])}
                self.assertEqual(self.apply([article], extracts), extracts)
        stale = copy.deepcopy(self.rules)
        stale['articleExtractionReviews'][0]['contentSha256'] = '0' * 64
        self.assertEqual(self.apply(rules=stale), self.extracts)

    def test_failed_or_pending_extraction_is_never_upgraded(self):
        for status in ('failed', 'pending'):
            with self.subTest(status=status):
                extracts = {self.article['id']: {'status': status, 'companies': [],
                    'modelAttempted': True, 'error': {'category': 'timeout'}}}
                self.assertEqual(self.apply(extracts=extracts), extracts)

    def test_empty_reviewed_companies_can_exclude_all_entities(self):
        self.decision['companies'] = []
        result = self.apply()[self.article['id']]
        self.assertEqual(result['companies'], [])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['articleExtractionReview']['contentSha256'], self.decision['contentSha256'])
        empty_raw = {self.article['id']: {'status': 'complete', 'companies': []}}
        self.assertEqual(self.apply(extracts=empty_raw)[self.article['id']]['companies'], [])

    def test_malformed_matched_rules_cannot_be_normalized_into_broad_replacements(self):
        changes = [
            lambda d: d.update(reason=''),
            lambda d: d.update(reviewedAt='not-a-date'),
            lambda d: d.update(extra='unsupported'),
            lambda d: d.update(companies={}),
            lambda d: d['companies'][0].update(company_name=''),
            lambda d: d['companies'][0].update(entity_type='person'),
            lambda d: d['companies'][0].update(country=['guess']),
            lambda d: d['companies'][0].update(industry_id='invalid'),
            lambda d: d['companies'][0].pop('aliases'),
            lambda d: d['companies'][0].update(unreviewed='extra'),
            lambda d: d['companies'][0]['products'][0].update(relationship='creator'),
            lambda d: d['companies'][0]['products'][0].update(quote='not in original evidence'),
            lambda d: d['companies'][0]['products'][0].update(quote=''),
            lambda d: d['companies'].append(copy.deepcopy(d['companies'][0])),
        ]
        for number, change in enumerate(changes):
            with self.subTest(number=number):
                decision = copy.deepcopy(self.decision)
                change(decision)
                with self.assertRaises(ValueError):
                    self.apply(rules={'articleExtractionReviews': [decision]})
        with self.assertRaisesRegex(ValueError, '多条'):
            self.apply(rules={'articleExtractionReviews': [self.decision, copy.deepcopy(self.decision)]})

    def test_funding_keeps_its_own_extraction_and_existing_field_reviews(self):
        rules = copy.deepcopy(self.rules)
        rules['fieldValueReviews'] = [{'articleId': self.article['id'], 'company': 'FundingCo',
            'field': 'valuation', 'from': '$1B', 'to': None, 'quote': self.article['content_text'],
            'reason': '原文不支持该估值'}]
        funding_extracts = {self.article['id']: {'status': 'complete', 'modelAttempted': False,
            'cacheHit': True, 'companies': [{'company_name': 'FundingCo', 'valuation': '$1B'}]}}
        original = copy.deepcopy(funding_extracts)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/quality_review.json').write_text(json.dumps(rules), encoding='utf-8')
            with patch.object(funding_table, 'PROJECT_ROOT', root), \
                    patch.object(funding_table, 'load_articles', return_value=[self.article]), \
                    patch.object(funding_table, 'extract_articles', return_value=funding_extracts):
                result = funding_table.build_funding_table(root / 'snapshot', root / 'feed', root / 'work',
                    TX, root / 'cache', skip_search=True)
        self.assertEqual([r['company_name'] for r in result['companies']], ['FundingCo'])
        self.assertIsNone(result['companies'][0]['valuation'])
        self.assertEqual(funding_extracts, original)
        self.assertEqual(result['stats']['modelCalls'], 0)


if __name__ == '__main__':
    unittest.main()
