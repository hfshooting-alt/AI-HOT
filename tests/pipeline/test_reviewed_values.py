import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from apply_quality_review import apply_article_value_reviews, apply_field_value_reviews
from company_index.entities import merge_entities
from funding.companies import merge_companies
import build_company_overview
import funding_table

TX = json.loads((ROOT / 'config/taxonomy.json').read_text(encoding='utf-8'))


class ReviewedValues(unittest.TestCase):
    def test_review_can_clear_an_unsupported_field_without_mutating_cache(self):
        article = {'id': 'single-round', 'content_text': '公司刚完成50亿美元融资。'}
        decision = {'company': 'Example', 'field': 'total_funding', 'from': '50亿美元',
                    'to': None, 'articleId': article['id'], 'quote': article['content_text'],
                    'reason': '只披露本轮金额，没有累计口径'}
        raw = {article['id']: {'status': 'complete', 'companies': [
            {'company_name': 'Example', 'total_funding': '50亿美元'}]}}
        reviewed = apply_article_value_reviews([article], raw, {'fieldValueReviews': [decision]})
        self.assertIsNone(reviewed[article['id']]['companies'][0]['total_funding'])
        self.assertEqual(raw[article['id']]['companies'][0]['total_funding'], '50亿美元')
        row = {'company_name': 'Example', 'total_funding': '50亿美元', 'fieldSources': {
            'total_funding': [{'value': '50亿美元', 'articleId': article['id'], 'origin': 'article'}]}}
        apply_field_value_reviews([row], {'fieldValueReviews': [decision]})
        self.assertIsNone(row['total_funding'])
        self.assertEqual(row['fieldSources']['total_funding'][0]['value'], '50亿美元')

    def setUp(self):
        self.decision = {'company': 'Example', 'field': 'valuation', 'from': '$3.7B',
                         'to': '拟议融资完成后可达 $3.7B', 'articleId': 'reviewed',
                         'quote': '完成后估值可达37亿美元', 'reason': '交易尚在谈判',
                         'reviewedAt': '2026-09-20'}
        self.rules = {'fieldValueReviews': [self.decision], 'aliases': {}, 'pending': {},
                      'classifications': {}, 'reviewedAt': '2026-09-20'}
        self.old = {'id': 'reviewed', 'publishedAt': '2026-09-18T09:00:00+08:00',
                    'title': 'Proposed financing', 'url': 'https://example.com/old',
                    'sourceName': 'Source', 'mpName': 'Source', 'category': 'financing',
                    'content_text': '融资尚在谈判，完成后估值可达 37 亿美元。'}
        self.new = {**self.old, 'id': 'new-confirmed', 'title': 'Financing completed',
                    'publishedAt': '2026-09-21T09:00:00+08:00',
                    'url': 'https://example.com/new', 'content_text': '融资已完成，估值37亿美元。'}
        self.company = {'company_name': 'Example', 'valuation': '$3.7B', 'entity_type': 'company'}
        self.extracts = {article['id']: {'status': 'complete', 'companies': [copy.deepcopy(self.company)]}
                         for article in (self.old, self.new)}

    def test_article_review_preserves_cached_values_and_is_idempotent(self):
        before = copy.deepcopy(self.extracts)
        reviewed = apply_article_value_reviews([self.old, self.new], self.extracts, self.rules)
        self.assertEqual(self.extracts, before)
        self.assertEqual(set(reviewed), set(self.extracts))
        self.assertEqual(reviewed['reviewed']['companies'][0]['valuation'], self.decision['to'])
        self.assertEqual(reviewed['new-confirmed']['companies'][0]['valuation'], '$3.7B')
        self.assertEqual(apply_article_value_reviews([self.old, self.new], reviewed, self.rules), reviewed)
        self.assertEqual(reviewed['reviewed']['companies'][0]['fieldValueReviews'], [self.decision])

    def test_review_requires_matching_article_company_value_and_current_quote(self):
        for change in ('article', 'company', 'value', 'quote'):
            with self.subTest(change=change):
                article = copy.deepcopy(self.old)
                extracts = copy.deepcopy(self.extracts)
                if change == 'article':
                    article['id'] = 'new-confirmed'
                elif change == 'company':
                    extracts['reviewed']['companies'][0]['company_name'] = 'Unrelated'
                elif change == 'value':
                    extracts['reviewed']['companies'][0]['valuation'] = '$5B'
                else:
                    article['content_text'] = '正文已更新，融资已完成。'
                before = copy.deepcopy(extracts)
                self.assertEqual(apply_article_value_reviews([article], extracts, self.rules), before)

    def test_new_confirmed_same_valuation_wins_in_both_mergers(self):
        for articles in ([self.old], [self.old, self.new], [self.new, self.old]):
            with self.subTest(article_ids=[a['id'] for a in articles]):
                reviewed = apply_article_value_reviews(articles, self.extracts, self.rules)
                expected = '$3.7B' if self.new in articles else self.decision['to']
                overview = merge_entities(articles, reviewed, {}, TX)
                funding = merge_companies(articles, reviewed)
                apply_field_value_reviews(overview, self.rules)
                apply_field_value_reviews(funding, self.rules)
                self.assertEqual(overview[0]['valuation'], expected)
                self.assertEqual(funding[0]['valuation'], expected)

    def test_legacy_review_requires_the_current_field_winner(self):
        old_source = {'articleId': 'reviewed', 'value': '$3.7B', 'origin': 'article',
                      'publishedAt': self.old['publishedAt']}
        new_source = {**old_source, 'articleId': 'new-confirmed', 'publishedAt': self.new['publishedAt']}
        current = {'company_name': 'Example', 'valuation': '$3.7B',
                   'fieldSources': {'valuation': [copy.deepcopy(old_source)]}}
        newer = {**copy.deepcopy(current), 'fieldSources': {'valuation': [new_source, copy.deepcopy(old_source)]}}
        wrong_value = {**copy.deepcopy(current), 'fieldSources': {'valuation': [{**old_source, 'value': '$1B'}]}}
        unrelated = {'company_name': 'Example', 'valuation': '$3.7B', 'sourceArticles': [{'id': 'reviewed'}]}
        ambiguous = {**copy.deepcopy(current), 'fieldSources': {'valuation': [
            copy.deepcopy(old_source), {**new_source, 'publishedAt': self.old['publishedAt']}]}}
        unknown_date = {**copy.deepcopy(current), 'fieldSources': {'valuation': [
            copy.deepcopy(old_source), {**new_source, 'publishedAt': ''}]}}
        untouched = [newer, wrong_value, unrelated, ambiguous, unknown_date]
        before = copy.deepcopy(untouched)
        apply_field_value_reviews([current, *untouched], self.rules)
        apply_field_value_reviews([current, *untouched], self.rules)
        self.assertEqual(current['valuation'], self.decision['to'])
        self.assertEqual(current['fieldValueReviews'], [self.decision])
        self.assertEqual(current['fieldSources']['valuation'][0]['originalValue'], '$3.7B')
        self.assertEqual(untouched, before)

    def test_builders_apply_reviews_before_merging_without_mutating_model_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config').mkdir()
            (root / 'config/quality_review.json').write_text(json.dumps(self.rules), encoding='utf-8')
            before = copy.deepcopy(self.extracts)
            stale_quote = {**self.old, 'content_text': '原报道已更新，融资已完成。'}
            for articles in ([self.old], [self.old, self.new], [stale_quote]):
                with self.subTest(article_count=len(articles)):
                    extracts = {a['id']: self.extracts[a['id']] for a in articles}
                    cost = {'modelCalls': 0, 'modelSuccesses': 0, 'cacheHits': len(articles), 'articlesDeferred': 0}
                    with patch.object(build_company_overview, 'ROOT', root), \
                            patch.object(build_company_overview, 'load_articles', return_value=articles), \
                            patch.object(build_company_overview, 'load_previous', return_value={}), \
                            patch.object(build_company_overview, 'extract_articles', return_value=(extracts, cost)), \
                            patch.object(funding_table, 'PROJECT_ROOT', root), \
                            patch.object(funding_table, 'load_articles', return_value=articles), \
                            patch.object(funding_table, 'extract_articles', return_value=extracts):
                        overview = build_company_overview.build(root/'snapshot', root/'feed', root/'work',
                            root/'previous', root/'overview-cache', TX, generated_at='2026-09-21T12:00:00+08:00')
                        funding = funding_table.build_funding_table(root/'snapshot', root/'feed', root/'work',
                            TX, root/'funding-cache', skip_search=True, generated_at='2026-09-21T12:00:00+08:00')
                    expected = self.decision['to'] if articles == [self.old] else '$3.7B'
                    self.assertEqual(overview['companies'][0]['valuation'], expected)
                    self.assertEqual(funding['companies'][0]['valuation'], expected)
            self.assertEqual(self.extracts, before)
