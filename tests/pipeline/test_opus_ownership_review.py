"""The reviewed comparison cannot be replayed as OpenAI ownership."""
import copy
import json
from pathlib import Path
import unittest

from apply_quality_review import apply, apply_product_exclusions
from company_index.entities import merge_entities
from company_index.extraction import normalize_company
from company_index.output import assemble


ROOT = Path(__file__).resolve().parents[2]


class OpusOwnershipReview(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads((ROOT / 'config/quality_review.json').read_text(encoding='utf-8'))
        self.tx = json.loads((ROOT / 'config/taxonomy.json').read_text(encoding='utf-8'))
        self.decision = next(d for d in self.rules['excludedProducts'] if d['company'] == 'OpenAI'
                             and d['name'] == 'Opus 5' and d['articleId'] == 'manus:0efa86ea4ce276bb')
        self.article = {'id': self.decision['articleId'], 'url': self.decision['url'],
                        'title': self.decision['title'], 'content_text': self.decision['quote'] + '。',
                        'publishedAt': '2026-09-20T12:38:47+08:00', 'dims': {}, 'category': 'bigtech'}
        self.openai = {'company_name': 'OpenAI', 'entity_type': 'company',
            'product_names': ['Opus 5', 'GPT-Live'], 'products': [
                {'name': 'Opus 5', 'relationship': 'owned', 'quote': self.decision['quote']},
                {'name': 'GPT-Live', 'relationship': 'unknown', 'quote': ''}]}
        self.anthropic = {'company_name': 'Anthropic', 'entity_type': 'company',
                          'product_names': ['Claude Opus 5']}
        self.extract = {'status': 'complete', 'companies': [normalize_company(c, self.tx)
                        for c in (self.openai, self.anthropic)]}

    def merged(self):
        return merge_entities([self.article], {self.article['id']: self.extract}, {'companies': []}, self.tx)

    def test_exact_association_only_and_existing_anthropic_and_gpt_live_survive(self):
        rows = self.merged()
        original = copy.deepcopy(rows)
        target = next(r for r in rows if r['company_name'] == 'OpenAI')
        removed = apply_product_exclusions(target, {'excludedProducts': [self.decision]})
        self.assertEqual([u['name'] for u in removed], ['Opus 5'])
        before = next(r for r in original if r['company_name'] == 'OpenAI')
        for key in set(target) - {'product_names', 'productUpdates', 'fieldSources'}:
            self.assertEqual(target[key], before[key])
        self.assertEqual(target['product_names'], ['GPT-Live'])
        self.assertEqual(target['productUpdates'], [u for u in before['productUpdates'] if u['name'] != 'Opus 5'])
        self.assertEqual(target['fieldSources']['company_name'], before['fieldSources']['company_name'])
        self.assertEqual(next(r for r in rows if r['company_name'] == 'Anthropic'),
                         next(r for r in original if r['company_name'] == 'Anthropic'))
        self.assertEqual(apply_product_exclusions(target, {'excludedProducts': [self.decision]}), [])

    def test_other_article_or_company_is_not_excluded_or_relabelled_integrated(self):
        for name, article_id in [('OpenAI', 'manus:another'), ('Anthropic', self.article['id'])]:
            row = next(r for r in self.merged() if r['company_name'] == 'OpenAI')
            row['company_name'] = name
            for update in row['productUpdates']:
                update['articleId'] = article_id
            for evidence in row['fieldSources']['product_names']:
                evidence['articleId'] = article_id
            original = copy.deepcopy(row)
            self.assertEqual(apply_product_exclusions(row, {'excludedProducts': [self.decision]}), [])
            self.assertEqual(row, original)

    def test_production_replay_removes_bad_success_again_without_mutating_cache(self):
        original = copy.deepcopy(self.extract)
        for _ in range(2):
            overview = assemble(self.merged(), {'modelCalls': 0, 'cacheHits': 1}, '2026-09-22T18:18:00+08:00')
            reviewed, _, _ = apply(overview, {}, self.rules, self.tx)
            target = next(r for r in reviewed['companies'] if r['company_name'] == 'OpenAI')
            self.assertNotIn('Opus 5', target['product_names'])
            self.assertFalse(any(u['name'] == 'Opus 5' for u in target['productUpdates']))
            self.assertFalse(any(e['value'] == 'Opus 5' for e in target['fieldSources']['product_names']))
            self.assertIn('GPT-Live', target['product_names'])
            self.assertIn('Claude Opus 5', next(r for r in reviewed['companies']
                                              if r['company_name'] == 'Anthropic')['product_names'])
            self.assertEqual((reviewed['stats']['modelCalls'], reviewed['stats']['cacheHits']), (0, 1))
            self.assertEqual(self.extract, original)
