"""Daily profile enrichment cannot bypass merge-time financial semantics."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from company_index.daily_research import enrich
from company_index.page_evidence import eligible_fact


def company():
    return {'id': 'company:example', 'company_name': 'Example', 'aliases': [],
            'product_names': [], 'fieldSources': {}, 'country': '美国',
            'business': '提供开发工具', 'founded': None, 'team': None,
            'total_funding': None, 'valuation': None,
            'firstSeenAt': '2026-09-20', 'lastSeenAt': '2026-09-20',
            'sourceArticles': [{'id': 'news', 'url': 'https://example.com/news'}]}


def fact(field, value, quote):
    return {'field': field, 'value': value, 'quote': quote,
            'url': 'https://example.com/about', 'title': 'About Example'}


class ResearchFinancialGate(unittest.TestCase):
    def test_single_round_and_fund_scope_in_either_value_or_quote_are_rejected(self):
        samples = [
            ('本轮融资总额1亿美元', 'Example本轮融资总额1亿美元。'),
            ('1亿美元', 'Example本轮融资总额1亿美元。'),
            ('累计融资1亿美元', 'Example本轮融资总额1亿美元。'),
            ('3.5亿美元C轮融资', 'Example累计融资5亿美元，其中C轮融资3.5亿美元。'),
            ('1.65亿美元首期基金', 'Example首期基金规模1.65亿美元。'),
            ('1.65亿美元', 'Example首期基金规模1.65亿美元。'),
            ('$150 million', 'Example raised $150 million in its seed round.'),
        ]
        for value, quote in samples:
            with self.subTest(value=value, quote=quote):
                self.assertIsNone(eligible_fact(fact('total_funding', value, quote), company()))

    def test_market_cap_cannot_be_laundered_as_a_bare_or_relabeled_valuation(self):
        for value, quote in (
            ('市值约600亿美元', 'Example市值约600亿美元。'),
            ('600亿美元', 'Example市值约600亿美元。'),
            ('估值600亿美元', 'Example市值约600亿美元。'),
            ('$60 billion', 'Example market capitalization reached $60 billion.'),
            ('market cap $60 billion', 'Example is worth $60 billion.'),
        ):
            with self.subTest(value=value, quote=quote):
                self.assertIsNone(eligible_fact(fact('valuation', value, quote), company()))

    def test_cumulative_and_annual_aggregate_keep_their_stated_time_precision(self):
        for value, quote in (
            ('累计融资接近1亿美元', 'Example累计融资接近1亿美元。'),
            ('2026 年完成合计近 2 亿美元融资', 'Example在2026年完成合计近2亿美元融资。'),
            ('截至2026年累计融资4亿美元', 'Example累计融资4亿美元，其中C轮融资3.5亿美元。'),
            ('$400 million total funding', 'Example total funding is $400 million including a Series C round.'),
            ('$400 million', 'Example has raised $400 million in total following its Series C round.'),
        ):
            proposal = fact('total_funding', value, quote)
            original = copy.deepcopy(proposal)
            with self.subTest(value=value):
                self.assertEqual(eligible_fact(proposal, company()), proposal)
                self.assertEqual(proposal, original)

    def test_legitimate_round_valuations_and_registration_year_are_unchanged(self):
        for value, quote in (
            ('2026年投后估值8亿美元', 'Example在2026年完成种子轮融资，投后估值8亿美元。'),
            ('$800 million valuation', 'Example completed a Series A round at an $800 million valuation.'),
        ):
            proposal = fact('valuation', value, quote)
            with self.subTest(value=value):
                self.assertEqual(eligible_fact(proposal, company()), proposal)
        registered_year = fact('founded', '2020', 'Example was incorporated in 2020.')
        self.assertEqual(eligible_fact(registered_year, company()), registered_year)
        self.assertIsNone(eligible_fact(fact('founded', '2020', 'The Example product launched in 2020.'), company()))

    def test_daily_enrichment_rejects_conflicting_financial_facts_and_accepts_valid_aggregate(self):
        source = company()
        raw_facts = [fact('valuation', '600亿美元', 'Example市值约600亿美元。'),
                     fact('total_funding', '1亿美元', 'Example本轮融资总额1亿美元。')]
        original = copy.deepcopy(source)
        proposal = Mock(return_value={'facts': raw_facts})
        reader = lambda u: {'url': u, 'title': 'About', 'text': 'Mocked quote-validated page'}
        with tempfile.TemporaryDirectory() as directory, patch('company_index.daily_research.resolve_model', return_value='offline-model'):
            result = enrich({'companies': [source]}, {}, directory, read_fn=reader, propose_fn=proposal, rules={})
            row = result['companies'][0]
            self.assertIsNone(row['valuation'])
            self.assertIsNone(row['total_funding'])
            self.assertEqual(result['knownLinkResearch']['filled'], 0)
            self.assertEqual(result['knownLinkResearch']['records'][0]['rejectedFacts'], 2)
            valid = fact('total_funding', '2026年完成合计近2亿美元融资', 'Example在2026年完成合计近2亿美元融资。')
            result = enrich({'companies': [source]}, {}, directory, read_fn=reader,
                            propose_fn=Mock(return_value={'facts': [valid]}), rules={})
            row = result['companies'][0]
            self.assertEqual(row['total_funding'], valid['value'])
            self.assertEqual(row['fieldSources']['total_funding'][0]['quote'], valid['quote'])
            self.assertEqual(row['fieldSources']['total_funding'][0]['verificationStatus'], 'provisional')
        self.assertEqual(source, original)


if __name__ == '__main__':
    unittest.main()
