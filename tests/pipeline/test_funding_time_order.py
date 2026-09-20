"""Funding values and display order follow real instants, not ISO spelling."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from funding.companies import merge_companies


def article(iid, published_at):
    return {'id': iid, 'title': iid, 'publishedAt': published_at,
            'url': 'https://example.com/' + iid}


def extraction(name, value):
    return {'status': 'complete', 'companies': [{'company_name': name, 'valuation': value}]}


class FundingTimeOrder(unittest.TestCase):
    def test_mixed_utc_and_beijing_orders_values_companies_and_sources(self):
        articles = [article('old', '2026-09-20T09:30:00+08:00'),
                    article('new', '2026-09-20T02:00:00Z'),
                    article('middle', '2026-09-20T09:45:00+08:00')]
        extracts = {'old': extraction('Example', 'old value'),
                    'new': extraction('Example', 'new value'),
                    'middle': extraction('Another', 'other value')}
        rows = merge_companies(articles, extracts)
        self.assertEqual([r['company_name'] for r in rows], ['Example', 'Another'])
        self.assertEqual(rows[0]['valuation'], 'new value')
        self.assertEqual([a['id'] for a in rows[0]['sourceArticles']], ['new', 'old'])
        self.assertEqual(rows[0]['sourceArticles'][0]['publishedAt'], '2026-09-20T02:00:00Z')

    def test_naive_time_is_beijing_instead_of_machine_local_time(self):
        articles = [article('naive', '2026-09-20T09:30:00'),
                    article('utc-new', '2026-09-20T02:00:00Z')]
        extracts = {'naive': extraction('Example', 'old value'),
                    'utc-new': extraction('Example', 'new value')}
        row = merge_companies(articles, extracts)[0]
        self.assertEqual(row['valuation'], 'new value')
        self.assertEqual([a['id'] for a in row['sourceArticles']], ['utc-new', 'naive'])

    def test_equivalent_instants_keep_input_order_and_first_nonempty_value(self):
        utc = article('utc', '2026-09-20T01:30:00Z')
        beijing = article('beijing', '2026-09-20T09:30:00+08:00')
        naive = article('naive', '2026-09-20T09:30:00')
        extracts = {a['id']: extraction('Example', a['id']) for a in (utc, beijing, naive)}
        for articles in ([utc, beijing, naive], [beijing, naive, utc], [naive, utc, beijing]):
            with self.subTest(first=articles[0]['id']):
                rows = merge_companies(articles, extracts)
                self.assertEqual(rows[0]['valuation'], articles[0]['id'])
                self.assertEqual([a['id'] for a in rows[0]['sourceArticles']], [a['id'] for a in articles])
                self.assertEqual(merge_companies(articles, extracts), rows)

    def test_equivalent_instants_keep_company_display_order(self):
        articles = [article('utc', '2026-09-20T01:30:00Z'),
                    article('beijing', '2026-09-20T09:30:00+08:00')]
        extracts = {'utc': extraction('First', 'first value'),
                    'beijing': extraction('Second', 'second value')}
        self.assertEqual([r['company_name'] for r in merge_companies(articles, extracts)], ['First', 'Second'])
