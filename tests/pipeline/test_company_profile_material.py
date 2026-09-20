import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import build_company_overview as overview


class ProfileMaterialTest(unittest.TestCase):
    def row(self):
        return {'id': 'company:test', 'company_name': 'Test', 'country': '中国',
            'profileUpdatedAt': '2026-09-19T12:00:00+08:00',
            'lastSeenAt': '2026-09-19T09:30:00+08:00',
            'product_names': ['A', 'B'],
            'productUpdates': [{'name': 'A', 'articleId': 'a'}, {'name': 'B', 'articleId': 'b'}],
            'fieldSources': {'country': [
                {'value': '中国', 'articleId': 'first', 'quote': '中国注册'},
                {'value': '中国', 'articleId': 'second', 'quote': '中国总部'}]}}

    def test_evidence_order_and_dict_key_order_do_not_change_profile(self):
        old = self.row()
        new = copy.deepcopy(old)
        new['fieldSources']['country'].reverse()
        new['fieldSources']['country'][0] = dict(reversed(list(new['fieldSources']['country'][0].items())))
        original = copy.deepcopy(new)
        self.assertEqual(overview.material_profile(old), overview.material_profile(new))
        self.assertEqual(new, original)

    def test_changed_evidence_and_duplicate_count_still_change_profile(self):
        for edit in ('quote', 'source', 'removed', 'duplicate'):
            old = self.row(); new = copy.deepcopy(old)
            if edit == 'quote': new['fieldSources']['country'][0]['quote'] = '新的逐字证据'
            if edit == 'source': new['fieldSources']['country'][0]['articleId'] = 'new-source'
            if edit == 'removed': new['fieldSources']['country'].pop()
            if edit == 'duplicate': new['fieldSources']['country'].append(copy.deepcopy(new['fieldSources']['country'][0]))
            with self.subTest(edit=edit):
                self.assertNotEqual(overview.material_profile(old), overview.material_profile(new))

    def test_facts_and_product_recency_order_remain_material(self):
        for field in ('country', 'product_names', 'productUpdates'):
            old = self.row(); new = copy.deepcopy(old)
            if field == 'country': new[field] = '美国'
            else: new[field].reverse()
            with self.subTest(field=field):
                self.assertNotEqual(overview.material_profile(old), overview.material_profile(new))

    def test_build_preserves_date_for_reordered_evidence_but_updates_changed_fact(self):
        for changed_fact in (False, True):
            old = self.row(); updated = copy.deepcopy(old)
            updated['fieldSources']['country'].reverse()
            if changed_fact: updated['country'] = '美国'
            now = '2026-09-20T22:28:44+08:00'
            built = {'companies': [updated], 'generatedAt': now}
            cost = dict(modelCalls=0, cacheHits=0, articlesDeferred=0)
            with self.subTest(changed_fact=changed_fact), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                for target, value in (
                    ('load_articles', []), ('extract_articles', ({}, cost)),
                    ('load_previous', {'companies': [old]}),
                    ('merge_entities', [updated]), ('apply_reviewed_research', [updated]),
                    ('assemble', built), ('validate', None)):
                    stack.enter_context(patch.object(overview, target, return_value=value))
                stack.enter_context(patch('apply_quality_review.apply_article_value_reviews', return_value={}))
                stack.enter_context(patch('apply_quality_review.apply', return_value=(built, {}, {})))
                model = Mock(side_effect=AssertionError('no API'))
                result = overview.build(None, None, None, None, Path(directory), {}, llm_fn=model, generated_at=now)
                model.assert_not_called()
            row = result['companies'][0]
            self.assertEqual(row['profileUpdatedAt'], now if changed_fact else old['profileUpdatedAt'])
            self.assertEqual(row['latestReportAt'], old['lastSeenAt'])
