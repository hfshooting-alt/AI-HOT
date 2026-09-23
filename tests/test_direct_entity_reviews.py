"""Editorial direct-source regressions using public quotes, with no raw bodies/API."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from apply_quality_review import apply, apply_article_value_reviews, _reviewed_companies
from company_index.entities import entity_id, merge_entities
from company_index.output import assemble
from funding.companies import normalize_company_key

TX = json.loads((ROOT / 'config/taxonomy.json').read_text(encoding='utf-8'))
IDS = ('direct:846997bed3ca7f17', 'direct:78809a7ab65d3d47',
       'direct:a05d15a9e341fcbd', 'direct:c35084ad0683f6aa',
       'direct:228bde7f718fd366', 'direct:70399b26c19c4a1e',
       'direct:df62230f0e98a993', 'direct:35fc19095d74af5c',
       'direct:d9032c6cd161096d', 'direct:3b1807dac01bf124',
       'direct:2ec66b9f14a56d39', 'direct:7f0007a0f1b362c2',
       'direct:8f26d8f551e8f681')


class DirectEntityReviewTests(unittest.TestCase):
    def setUp(self):
        rules = json.loads((ROOT / 'config/quality_review.json').read_text(encoding='utf-8'))
        self.decisions = {d['articleId']: d for d in rules['articleExtractionReviews']
                          if d['articleId'] in IDS}
        self.assertEqual(set(self.decisions), set(IDS))

    def fixture(self, article_id, date='2026-09-23T10:00:00+08:00'):
        decision = copy.deepcopy(self.decisions[article_id])
        # CI has no private complete source body. Exercise normalization and
        # replay with public reviewed quotes under a freshly bound test hash.
        # Actual saved-body hashes are checked by the private editorial audit.
        body = '\n'.join(p['quote'] for c in decision['companies'] for p in c['products'])
        decision['contentSha256'] = hashlib.sha256(body.encode()).hexdigest()
        article = dict(id=article_id, title=decision['title'], url=decision['url'],
                       content_text=body, publishedAt=date, sourceName='离线审核夹具', category='general')
        result = {'status': 'complete', 'modelAttempted': False, 'cacheHit': True,
                  'companies': []}
        extracts = {article_id: result}
        reviewed = apply_article_value_reviews([article], extracts, {'articleExtractionReviews': [decision]})
        self.assertEqual(result['companies'], [])  # successful cache is unchanged
        self.assertFalse(reviewed[article_id]['modelAttempted'])
        return article, reviewed, decision

    def assembled(self, articles, extracts, previous=None):
        rows = merge_entities(articles, extracts, previous or {}, TX, research_rules={})
        overview = assemble(rows, {}, '2026-09-23T12:00:00+08:00')
        with patch('apply_quality_review.apply_reviewed_research', side_effect=copy.deepcopy):
            return apply(overview, {}, {'aliases': {}, 'pending': {}, 'classifications': {},
                                       'reviewedAt': '2026-09-23'}, TX)[0]

    def test_all_bound_projections_are_lossless_and_stale_body_cannot_apply(self):
        for article_id in IDS:
            with self.subTest(article_id=article_id):
                article, reviewed, decision = self.fixture(article_id)
                companies = reviewed[article_id]['companies']
                self.assertEqual(_reviewed_companies(article, companies), companies)
                stale = {**article, 'content_text': article['content_text'] + '\nchanged'}
                cached = {article_id: {'status': 'complete', 'companies': [], 'modelAttempted': False}}
                self.assertEqual(apply_article_value_reviews([stale], cached,
                    {'articleExtractionReviews': [decision]}), cached)

    def test_authors_never_become_companies_but_named_outputs_survive_pending(self):
        article, extracts, _ = self.fixture(IDS[1])
        overview = self.assembled([article], extracts)
        all_names = {c['company_name'] for b in ('companies', 'pendingEntities') for c in overview[b]}
        self.assertFalse(all_names & {'larryvrh', 'TuTu_1018', 'Jojocodex', '山音', 'Pieter Levels'})
        pending = {c['company_name']: c for c in overview['pendingEntities']}
        for name in ('Turbo LoRA', '电影质感LoRA', 'Camera Motion LoRA',
                     'Wushu Action LoRA', 'Spatial Physics LoRA', '离婚记'):
            self.assertEqual(pending[name]['entityType'], 'product')
            self.assertEqual(pending[name]['sourceArticles'][0]['id'], article['id'])
            self.assertEqual(pending[name]['productUpdates'][0]['relationship'], 'unknown')

    def test_two_model_comparisons_do_not_promote_pending_qwen_to_a_company(self):
        first, first_results, _ = self.fixture(IDS[5], '2026-09-23T09:00:00+08:00')
        second, second_results, _ = self.fixture(IDS[6], '2026-09-23T10:00:00+08:00')
        initial = self.assembled([first], first_results)
        previous = {'companies': initial['companies'] + initial['pendingEntities']}
        final = self.assembled([second], second_results, previous)
        self.assertNotIn('Qwen', {c['company_name'] for c in final['companies']})
        qwen = next(c for c in final['pendingEntities'] if c['company_name'] == 'Qwen')
        self.assertEqual({a['id'] for a in qwen['sourceArticles']}, {first['id'], second['id']})
        self.assertTrue(qwen['productUpdates'])
        self.assertTrue(all(p['relationship'] == 'unknown' for p in qwen['productUpdates']))
        third, third_results, _ = self.fixture(IDS[8], '2026-09-23T11:00:00+08:00')
        newest = self.assembled([third], third_results,
            {'companies': final['companies'] + final['pendingEntities']})
        self.assertNotIn('Qwen', {c['company_name'] for c in newest['companies']})
        pending_names = {c['company_name'] for c in newest['pendingEntities']}
        self.assertTrue({'Qwen', 'Blender', 'Franka Panda'} <= pending_names)

    def test_relationship_direction_nonproducts_and_parent_business_are_preserved(self):
        def product(article_id, company, name):
            row = next(c for c in self.decisions[article_id]['companies'] if c['company_name'] == company)
            return next(p for p in row['products'] if p['name'] == name)
        self.assertEqual(product(IDS[0], '阿里巴巴', 'SGLang')['relationship'], 'used')
        self.assertEqual(product(IDS[1], '英伟达', 'Sol Engine')['relationship'], 'used')
        self.assertEqual(product(IDS[4], 'Anthropic', 'Claude')['relationship'], 'owned')
        for article_id, banned in ((IDS[0], {'新款GPU'}), (IDS[2], {'Harness'}),
                                   (IDS[3], {'AI创作浪潮计划', '抖音AI创作大赛'})):
            names = {p for c in self.decisions[article_id]['companies'] for p in c['product_names']}
            self.assertFalse(names & banned)
        article, extracts, _ = self.fixture(IDS[2])
        previous = {'companies': [{'id': entity_id(normalize_company_key('阿里巴巴')),
            'company_name': '阿里巴巴', 'entityType': 'company', 'business': '已审核的母公司综合业务',
            'dims': {'行业': '其他AI应用', '国家/地区': '中国'},
            'lastSeenAt': '2026-09-22T08:00:00+08:00'}]}
        overview = self.assembled([article], extracts, previous)
        names = {c['company_name'] for b in ('companies', 'pendingEntities') for c in overview[b]}
        self.assertNotIn('千问办公', names)
        ali = next(c for c in overview['companies'] if c['company_name'] == '阿里巴巴')
        self.assertEqual(ali['business'], '已审核的母公司综合业务')
        self.assertIn('千问办公', ali['product_names'])
        self.assertIn('MyContext', ali['product_names'])

    def test_recovered_articles_cannot_restore_methods_company_duplicates_or_parent_valuation(self):
        def rows(article_id):
            return {c['company_name']: c for c in self.decisions[article_id]['companies']}
        robot = rows(IDS[7])
        self.assertFalse({'CoMo', 'HuRo', 'Rhoda'} & set(robot))
        self.assertIn('Light-O1', robot['亮源新创']['product_names'])
        self.assertIn('Helix 2.5', robot['Figure']['product_names'])
        roundup = rows(IDS[9])
        self.assertIsNone(roundup['理想汽车']['valuation'])
        self.assertNotIn('千问', roundup)
        self.assertIn('Qwen Intelligence', roundup['阿里巴巴']['product_names'])
        office = rows(IDS[10])
        self.assertNotIn('千问办公', office)
        self.assertIn('QwenNote A2', office['阿里巴巴']['product_names'])
        erpa = next(p for p in rows(IDS[11])['Product LATAM']['products'] if p['name'] == 'ERPA')
        self.assertEqual(erpa['relationship'], 'used')
        self.assertNotIn('Aeon', rows(IDS[12])['OpenAI']['product_names'])


if __name__ == '__main__':
    unittest.main()
