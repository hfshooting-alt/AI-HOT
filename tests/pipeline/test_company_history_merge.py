"""Historical backfills retain newer company facts while adding source links."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from company_index.entities import merge_entities

TX = json.loads((ROOT / 'config/taxonomy.json').read_text(encoding='utf-8'))


class CompanyHistoryMergeTest(unittest.TestCase):
    def article(self, article_id, day):
        return {'id': article_id, 'title': article_id,
                'url': 'https://example.com/' + article_id,
                'publishedAt': f'2026-09-{day:02d}T12:00:00+08:00'}

    def extraction(self, **changes):
        return {'company_name': 'Example', 'aliases': [], 'entity_type': 'company',
                'country': '美国', 'business': '当前业务', 'industry_id': 'ai_other',
                'product_names': [], 'products': [], **changes}

    def merge(self, article, extraction, previous=None):
        return merge_entities([article], {article['id']: {'companies': [extraction]}},
                              previous or {}, TX)

    def test_older_article_preserves_newer_type_country_and_scalar(self):
        latest = self.article('latest', 20)
        previous = {'companies': self.merge(latest, self.extraction())}
        original = copy.deepcopy(previous)
        old = self.article('historical', 18)
        row = self.merge(old, self.extraction(entity_type='product', country='中国',
                                              business='旧业务'), previous)[0]
        self.assertEqual(row['entityType'], 'company')
        self.assertEqual(row['country'], '美国')
        self.assertEqual(row['dims']['国家/地区'], '美国')
        self.assertEqual(row['business'], '当前业务')
        self.assertEqual(row['lastSeenAt'], latest['publishedAt'])
        self.assertEqual(row['firstSeenAt'], old['publishedAt'])
        self.assertEqual([a['id'] for a in row['sourceArticles']], ['latest', 'historical'])
        self.assertEqual(previous, original)

    def test_older_article_can_fill_missing_type_and_country(self):
        latest = self.article('latest', 20)
        previous = {'companies': self.merge(latest, self.extraction(country=None))}
        previous['companies'][0].pop('entityType')
        row = self.merge(self.article('historical', 18),
                         self.extraction(entity_type='foundation', country='中国'), previous)[0]
        self.assertEqual(row['entityType'], 'foundation')
        self.assertEqual(row['country'], '中国')
        self.assertEqual(row['dims']['国家/地区'], '中国')
        self.assertEqual(row['lastSeenAt'], latest['publishedAt'])

    def test_newer_article_can_update_type_and_country(self):
        previous = {'companies': self.merge(self.article('historical', 18), self.extraction())}
        row = self.merge(self.article('latest', 20),
                         self.extraction(entity_type='foundation', country='中国'), previous)[0]
        self.assertEqual(row['entityType'], 'foundation')
        self.assertEqual(row['country'], '中国')
        self.assertEqual(row['dims']['国家/地区'], '中国')

    def test_newer_article_without_country_keeps_selected_country_dimension(self):
        previous = {'companies': self.merge(self.article('historical', 18), self.extraction())}
        row = self.merge(self.article('latest', 20), self.extraction(country=None), previous)[0]
        self.assertEqual(row['country'], '美国')
        self.assertEqual(row['dims']['国家/地区'], '美国')

    def test_newer_product_alias_keeps_company_type(self):
        previous = {'companies': self.merge(self.article('historical', 18),
                                            self.extraction(aliases=['Example App']))}
        row = self.merge(self.article('latest', 20),
                         self.extraction(company_name='Example App', entity_type='product'), previous)[0]
        self.assertEqual(row['entityType'], 'company')
        self.assertEqual(row['company_name'], 'Example')
        self.assertEqual([a['id'] for a in row['sourceArticles']], ['latest', 'historical'])


if __name__ == '__main__':
    unittest.main()
