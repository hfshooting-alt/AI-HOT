import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from apply_quality_review import apply, fingerprint
import tag_news


class QualityReviewTests(unittest.TestCase):
    def setUp(self):
        self.tx = tag_news.load_taxonomy('config/taxonomy.json')
        self.rules = dict(reviewedAt='2026-09-10', aliases={}, pending={}, classifications={})
        self.overview = dict(companies=[], stats={}, coverageNote='test')

    @patch('apply_quality_review.validate')
    def test_changed_article_is_not_overridden(self, _):
        item = dict(id='x', title='预告', summary='计划发布')
        self.rules['classifications']['x'] = dict(fingerprint=fingerprint(item), category='general', reason='预告')
        item['summary'] = '现已正式发布'
        _, s, audit = apply(self.overview, {'all': {'items': [item]}}, self.rules, self.tx)
        self.assertNotIn('classification', s['all']['items'][0])
        self.assertEqual(audit['staleDecisions'], ['x'])

    @patch('apply_quality_review.validate')
    def test_updates_all_views_and_keeps_original(self, _):
        item = dict(id='x', title='预告', summary='计划发布')
        self.rules['classifications']['x'] = dict(fingerprint=fingerprint(item), category='general', reason='预告')
        s = dict(all={'items': [item]}, daily={'sections': [{'label': '产品和模型发布', 'items': [item]}]})
        original = copy.deepcopy(s)
        _, result, audit = apply(self.overview, s, self.rules, self.tx)
        self.assertEqual(s, original)
        self.assertEqual(result['all']['items'][0]['classification']['cat'], 'general')
        self.assertEqual(result['daily']['sections'][0]['label'], '泛行业新闻')
        self.assertEqual(len(audit['classifications']), 1)

    @patch('apply_quality_review.validate')
    def test_pending_record_is_preserved(self, _):
        self.overview['companies'] = [dict(company_name='Model', sourceArticles=[{'id':'article'}])]
        self.rules['pending']['Model'] = 'product'
        result, _, _ = apply(self.overview, {}, self.rules, self.tx)
        self.assertEqual(result['companies'], [])
        self.assertEqual(result['pendingEntities'][0]['sourceArticles'], [{'id':'article'}])


if __name__ == '__main__':
    unittest.main()
