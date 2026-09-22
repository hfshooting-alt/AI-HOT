"""Reviewed identities cannot reintroduce retired or absent news evidence."""
import copy
import json
from pathlib import Path
import unittest

from apply_quality_review import apply
from company_index.identity import apply_reviewed_research


ROOT = Path(__file__).resolve().parents[2]


class ReviewedArticleProvenance(unittest.TestCase):
    def setUp(self):
        self.article = {'id': 'manus:retained', 'url': 'https://example.com/report',
                        'title': 'Report', 'publishedAt': '2026-09-20T09:00:00+08:00'}
        self.row = {'id': 'company:owner', 'company_name': 'Owner', 'aliases': [],
                    'product_names': [], 'productUpdates': [], 'fieldSources': {},
                    'sourceArticles': [self.article], 'country': None,
                    'firstSeenAt': self.article['publishedAt'], 'lastSeenAt': self.article['publishedAt']}
        self.article_fact = {'field': 'owner_company', 'value': 'Owner', 'origin': 'article',
            'articleId': self.article['id'], 'url': self.article['url'], 'title': 'Report',
            'quote': 'Product is made by Owner', 'checkedAt': '2026-09-20'}
        self.rules = {'checkedAt': '2026-09-10', 'records': [{'record_name': 'Product',
            'owner_company': 'Owner', 'reviewed': True, 'facts': [self.article_fact]}]}

    def test_owner_alone_does_not_resurrect_retired_or_absent_article_facts(self):
        for article_id, url in [('aihot:retired', self.article['url']),
                                ('manus:absent', self.article['url']),
                                (self.article['id'], 'https://example.com/different')]:
            with self.subTest(article_id=article_id, url=url):
                self.article_fact.update(articleId=article_id, url=url)
                original = copy.deepcopy(self.row)
                result = apply_reviewed_research([self.row], self.rules)
                self.assertEqual(result[0]['fieldSources'], {})
                self.assertEqual(result[0]['sourceArticles'], original['sourceArticles'])
                self.assertEqual(self.row, original)
                self.assertEqual(apply_reviewed_research(result, self.rules), result)

    def test_active_manus_fact_and_independent_official_research_remain_eligible(self):
        self.rules['records'][0]['facts'].append({'field': 'country', 'value': '美国',
            'url': 'https://example.com/official', 'title': 'Official', 'quote': 'US headquarters',
            'checkedAt': '2026-09-12'})
        result = apply_reviewed_research([self.row], self.rules)
        fields = result[0]['fieldSources']
        self.assertEqual(fields['company_name'][0]['articleId'], 'manus:retained')
        self.assertEqual(fields['country'][0]['origin'], 'research')
        self.assertEqual(fields['country'][0]['checkedAt'], '2026-09-12')
        self.assertEqual(result[0]['country'], '美国')
        self.assertEqual(apply_reviewed_research(result, self.rules), result)

    def test_retired_scalar_fact_cannot_fill_or_replace_current_value(self):
        self.article_fact.update(field='country', value='美国', replace=True, articleId='aihot:retired')
        for value in (None, '中国'):
            self.row['country'] = value
            result = apply_reviewed_research([self.row], self.rules)
            self.assertEqual(result[0]['country'], value)
            self.assertNotIn('country', result[0]['fieldSources'])

    def test_retired_article_does_not_delete_identity_rule_or_inject_owned_evidence(self):
        product = copy.deepcopy(self.row)
        product.update(id='company:product', company_name='Product', product_names=['Product'],
                       productUpdates=[{**self.article, 'articleId': self.article['id'],
                                        'name': 'Product', 'relationship': 'unknown'}])
        self.article_fact['articleId'] = 'aihot:retired'
        self.rules['records'][0]['owned_products'] = ['Product']
        result = apply_reviewed_research([self.row, product], self.rules)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['company_name'], 'Owner')
        self.assertIn('Product', result[0]['aliases'])
        self.assertIn('Product', result[0]['brandProfiles'])
        self.assertEqual(result[0]['productUpdates'][0]['relationship'], 'unknown')
        self.assertNotIn('ownershipEvidence', result[0]['productUpdates'][0])
        self.assertEqual(result[0]['fieldSources'].get('company_name', []), [])

    def test_real_config_is_safe_on_repeated_quality_review(self):
        from company_index.entities import merge_entities
        from company_index.extraction import normalize_company
        from company_index.output import assemble
        tx = json.loads((ROOT / 'config/taxonomy.json').read_text(encoding='utf-8'))
        names = ('OpenAI', 'Anthropic', 'Google', 'Meta', 'xAI', '阿里巴巴')
        extract = {'status': 'complete', 'companies': [normalize_company(
            {'company_name': name, 'entity_type': 'company'}, tx) for name in names]}
        article = {**self.article, 'dims': {}, 'category': 'general'}
        rows = merge_entities([article], {article['id']: extract}, {'companies': []}, tx)
        overview = assemble(rows, {}, '2026-09-22T18:18:00+08:00')
        quality = {'aliases': {}, 'pending': {}, 'classifications': {}}
        # Use the production config and both production review entry points.
        overview['companies'] = apply_reviewed_research(overview['companies'])
        once, _, _ = apply(overview, {}, quality, tx)
        twice, _, _ = apply(once, {}, quality, tx)
        for row in twice['companies']:
            for evidence in row['fieldSources'].values():
                self.assertFalse(any(e.get('articleId', '').startswith('aihot:') for e in evidence))
        self.assertEqual(twice['companies'], once['companies'])
        self.assertEqual(twice['stats'], once['stats'])
