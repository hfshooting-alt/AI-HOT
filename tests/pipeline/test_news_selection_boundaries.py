"""Two publication pools cannot silently widen paid company/funding inputs."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_company_overview as overview
import tag_news
from automation import candidate
from automation.publish import save
from automation.runner import validate_news_pools, validate_candidates
from company_index.inputs import load_articles as company_articles
from funding.inputs import load_articles as funding_articles
from review_all_scanned import review_pool_items

TX = tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
WINDOW = {'start': '2026-09-21T09:30:00+08:00', 'end': '2026-09-22T09:30:00+08:00'}


def raw(article_id, category='financing', selected=True):
    return {'id': article_id, 'title': '测试企业发布人工智能产品',
            'summary': '测试企业发布新的人工智能产品，原文披露产品功能与业务进展。' * 8,
            'url': f'https://example.com/{article_id}', 'publishedAt': '2026-09-22T08:00:00+08:00',
            'classification': {'category': category, 'tags': {}, 'autoFallback': False},
            'garenaSelection': {'status': 'selected' if selected else 'excluded'}}


def public(item, num=1):
    return {**copy.deepcopy(item), 'classification': tag_news.to_display(TX, item['classification']), 'num': num}


def pools(selected=None):
    selected = [raw('aihot:selected')] if selected is None else selected
    other = raw('aihot:unselected', selected=False)
    all_articles = [other, *copy.deepcopy(selected)]
    status = {'collectionWindow': WINDOW, 'sources': [{'status': 'complete'}],
              'publishedArticles': len(selected), 'articleLibraryCount': len(all_articles),
              'candidateArticles': len(all_articles), 'excludedArticles': 1,
              'quarantinedArticles': 0, 'quarantined': []}
    processed = {'collectionWindow': WINDOW, 'collectionStatus': status,
                 'items': selected, 'allArticles': all_articles}
    snap = {'newsSelectionVersion': 1, 'collectionWindow': WINDOW, 'collectionStatus': status,
            'garenaSelected': {'items': [public(a, i + 1) for i, a in enumerate(selected)]},
            'all': {'items': [public(a, i + 1) for i, a in enumerate(all_articles)]},
            'daily': {'sections': [{'items': [public(other)]}]},
            'weekly': {'sections': [{'items': [public(other)]}]}, 'history': [], 'weeklyNav': []}
    return snap, processed


class SelectionInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / 'snapshot.json'
        self.feed = self.root / 'feed.json'
        save(self.feed, {'ok': True, 'items': [raw('manus:feed-only')]})

    def load(self, loader):
        return loader(self.snapshot, self.feed, self.root / 'work', TX)

    def test_new_inputs_only_use_selected_and_financing_subset(self):
        selected = [raw('aihot:financing'), raw('aihot:release', category='release')]
        snap, _ = pools(selected)
        save(self.snapshot, snap)
        self.assertEqual({a['id'] for a in self.load(company_articles)}, {'aihot:financing', 'aihot:release'})
        self.assertEqual([a['id'] for a in self.load(funding_articles)], ['aihot:financing'])

    def test_explicit_empty_selection_does_not_fall_back(self):
        snap, _ = pools([])
        save(self.snapshot, snap)
        for loader in (company_articles, funding_articles):
            with self.subTest(loader=loader.__module__):
                self.assertEqual(self.load(loader), [])

    def test_manual_review_updates_only_selected_and_its_library_copy(self):
        snap, _ = pools()
        self.assertEqual([a['id'] for a in review_pool_items(snap)], ['aihot:selected', 'aihot:selected'])
        self.assertIs(review_pool_items(snap)[0], snap['garenaSelected']['items'][0])
        snap, _ = pools([])
        self.assertEqual(review_pool_items(snap), [])

    def test_missing_or_invalid_selection_is_rejected(self):
        for version, selected in ((1, None), (1, {'items': None}), (2, {'items': []}), (True, {'items': []})):
            snap, _ = pools([])
            snap['newsSelectionVersion'] = version
            snap['garenaSelected'] = selected
            save(self.snapshot, snap)
            for loader in (company_articles, funding_articles):
                with self.subTest(version=version, selected=selected, loader=loader.__module__):
                    with self.assertRaisesRegex(ValueError, '精选池'):
                        self.load(loader)

    def test_legacy_snapshot_keeps_history_and_feed_compatibility(self):
        old = public(raw('aihot:history'))
        save(self.snapshot, {'daily': {'sections': [{'items': [old]}]}, 'weekly': {'sections': []}})
        for loader in (company_articles, funding_articles):
            self.assertEqual({a['id'] for a in self.load(loader)}, {'aihot:history', 'manus:feed-only'})

    def test_empty_selection_preserves_historical_company_and_research_state(self):
        snap, _ = pools()
        save(self.snapshot, snap)
        previous = self.root / 'previous.json'
        model = Mock(return_value=json.dumps({'companies': [{'company_name': '回归测试星海科技',
            'entity_type': 'company', 'business': 'AI产品研发', 'product_names': [], 'aliases': [],
            'industry_id': 'ai_other'}]}, ensure_ascii=False))
        first = overview.build(self.snapshot, self.feed, self.root / 'work', previous,
                               self.root / 'cache', TX, llm_fn=model, generated_at='2026-09-22T10:00:00+08:00')
        self.assertEqual(model.call_count, 1)
        self.assertEqual(first['stats']['companiesTotal'], 1)
        first['knownLinkResearchState'] = {'existing': {'status': 'completed', 'checkedAt': '2026-09-22T10:00:00+08:00'}}
        first['companyDiscovery'] = {'history': {'existing': {'status': 'complete'}}}
        save(previous, first)
        snap, _ = pools([])
        save(self.snapshot, snap)
        never_call = Mock(side_effect=AssertionError('empty selection called model'))
        result = overview.build(self.snapshot, self.feed, self.root / 'work', previous,
                                self.root / 'cache', TX, llm_fn=never_call, generated_at='2026-09-23T10:00:00+08:00')
        never_call.assert_not_called()
        self.assertEqual(result['companies'], first['companies'])
        self.assertEqual(result['knownLinkResearchState'], first['knownLinkResearchState'])
        self.assertEqual(result['companyDiscovery'], first['companyDiscovery'])
        self.assertEqual(result['stats']['articlesProcessed'], 0)


class PoolValidation(unittest.TestCase):
    def test_full_pool_can_be_larger_and_numbered_independently(self):
        snap, prepared = pools()
        chosen, library = validate_news_pools(snap, prepared, TX)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(len(library), 2)
        self.assertEqual(chosen[0]['num'], 1)
        self.assertEqual(library[1]['num'], 2)

    def test_empty_selected_pool_is_valid_with_nonempty_library(self):
        snap, prepared = pools([])
        chosen, library = validate_news_pools(snap, prepared, TX)
        self.assertEqual(chosen, [])
        self.assertEqual(len(library), 1)

    def test_new_schema_requires_both_pools_and_version(self):
        for target, key in (('snapshot', 'garenaSelected'), ('snapshot', 'all'),
                            ('snapshot', 'newsSelectionVersion'), ('processed', 'allArticles')):
            snap, prepared = pools()
            del (snap if target == 'snapshot' else prepared)[key]
            with self.subTest(target=target, key=key), self.assertRaises(ValueError):
                validate_news_pools(snap, prepared, TX)

    def test_candidate_article_content_and_classification_are_bound(self):
        for key, value in (('summary', 'changed'), ('classification', None),
                           ('garenaSelection', {'status': 'excluded'}), ('content_text', 'private body')):
            snap, prepared = pools()
            snap['all']['items'][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_news_pools(snap, prepared, TX)

    def test_selected_record_cannot_have_other_conflicting_public_metadata(self):
        snap, prepared = pools()
        snap['garenaSelected']['items'][0]['source'] = 'different source'
        with self.assertRaisesRegex(ValueError, '两池共用文章'):
            validate_news_pools(snap, prepared, TX)

    def test_selected_must_be_superset_member_even_if_each_pool_matches_its_input(self):
        snap, prepared = pools()
        prepared['allArticles'].pop()
        snap['all']['items'].pop()
        with self.assertRaisesRegex(ValueError, '包含所有精选'):
            validate_news_pools(snap, prepared, TX)

    def test_duplicate_ids_and_wrong_library_count_are_rejected(self):
        snap, prepared = pools()
        snap['all']['items'].append(copy.deepcopy(snap['all']['items'][0]))
        with self.assertRaisesRegex(ValueError, '重复'):
            validate_news_pools(snap, prepared, TX)
        snap, prepared = pools()
        prepared['collectionStatus']['articleLibraryCount'] = 1
        with self.assertRaisesRegex(ValueError, '全部文章计数'):
            validate_news_pools(snap, prepared, TX)

    def test_review_candidate_counts_companies_against_selected_not_library(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(candidate, 'validate_candidates'):
            root = Path(temp)
            workspace = root / 'work/candidate'
            (root / 'config').mkdir()
            shutil.copyfile(ROOT / 'config/taxonomy.json', root / 'config/taxonomy.json')
            snap, prepared = pools()
            save(workspace / 'inputs/processed.json', prepared)
            save(workspace / 'web/public/snapshot.json', snap)
            save(workspace / 'data/manus/current.json', {'collectionStatus': prepared['collectionStatus']})
            overview_data = {'stats': {'articlesProcessed': 1, 'companiesTotal': 3}}
            save(workspace / 'data/company-overview/current.json', overview_data)
            result = candidate.validate(workspace, root)
            self.assertEqual(result['news'], 1)
            self.assertEqual(result['articleLibraryCount'], 2)
            overview_data['stats']['articlesProcessed'] = 2
            save(workspace / 'data/company-overview/current.json', overview_data)
            with self.assertRaisesRegex(ValueError, '公司处理范围'):
                candidate.validate(workspace, root)

    def test_runner_enforces_two_pool_gate_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            snap, prepared = pools()
            save(workspace / 'inputs/processed.json', prepared)
            save(workspace / 'web/public/snapshot.json', snap)
            save(workspace / 'data/manus/current.json', {
                'schemaVersion': 2, 'targetDate': '2026-09-22', 'generatedAt': '2026-09-22T10:00:00+08:00',
                'collector': 'manus', 'ok': True, 'degraded': False, 'items': [],
                'stats': dict.fromkeys(('configuredAccounts', 'completeAccounts', 'failedAccounts',
                                       'discoveredArticles', 'publishedArticles', 'fallbackArticles'), 0)})
            validate_candidates(workspace, ROOT, ['news', 'snapshot'])
            snap['garenaSelected']['items'] = []
            save(workspace / 'web/public/snapshot.json', snap)
            with self.assertRaisesRegex(ValueError, '新闻与网页批次不一致'):
                validate_candidates(workspace, ROOT, ['news', 'snapshot'])


if __name__ == '__main__':
    unittest.main()
