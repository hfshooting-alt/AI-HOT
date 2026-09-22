"""Source removal must not leak AIHOT facts or rewrite budgets/old artifacts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import manus_only_migration as migration


def article(iid, collector, **kwargs):
    return {'id': iid, 'collector': collector, 'url': 'https://example.com/' + iid,
            'title': iid, 'publishedAt': '2026-09-21T12:00:00+08:00',
            'mpName': '测试媒体', 'classification': {'cat': 'general'},
            'garenaSelection': {'status': 'selected'}, **kwargs}


def evidence(article, value, **kwargs):
    return {'articleId': article['id'], 'url': article['url'], 'title': article['title'],
            'publishedAt': article['publishedAt'], 'origin': 'article', 'value': value, **kwargs}


def entity(a, m=None):
    rows = [a] + ([m] if m else [])
    return {'id': 'company:test', 'company_name': '保留公司', 'aliases': [],
        'entityType': 'company', 'sourceArticles': rows,
        'fieldSources': {'company_name': [evidence(x, '保留公司') for x in rows],
            'business': [evidence(a, 'AIHOT业务')] + ([evidence(m, 'Manus业务')] if m else []),
            'product_names': [evidence(a, 'AIHOT产品')] + ([evidence(m, 'Manus产品')] if m else [])},
        'business': 'AIHOT业务', 'founded': None, 'country': None, 'team': None,
        'investors': None, 'total_funding': None, 'valuation': None,
        'product_names': ['AIHOT产品'] + (['Manus产品'] if m else []),
        'productUpdates': [{'name': 'AIHOT产品', 'relationship': 'owned', 'quote': '开发AIHOT产品',
                           'articleId': a['id'], 'url': a['url']}]
                         + ([{'name': 'Manus产品', 'relationship': 'owned', 'quote': '开发Manus产品',
                             'articleId': m['id'], 'url': m['url']}] if m else []),
        'dims': {'行业': 'AI模型', '国家/地区': '其他'},
        'profileUpdatedAt': '2026-09-20T10:00:00+08:00'}


class ManusOnlyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.a = article('aihot:a', 'aihot')
        self.m = article('manus:m', 'manus', publishedAt='2026-09-20T12:00:00+08:00')
        self.provenance = migration.Provenance([{'items': [self.a, self.m]}])
        self.checked = '2026-09-22T19:00:00+08:00'

    def test_same_publisher_name_does_not_turn_aihot_into_manus(self):
        self.assertIsNone(self.provenance.article(self.a))
        self.assertEqual(self.provenance.article(self.m)['id'], 'manus:m')
        unknown = article('legacy-unknown', '', mpName=self.m['mpName'])
        self.assertIsNone(self.provenance.article(unknown))

    def test_mixed_company_keeps_manus_facts_and_independent_research(self):
        row = entity(self.a, self.m)
        row['country'] = '美国'
        research = {'value': '美国', 'articleId': 'research:country', 'origin': 'research',
                    'url': 'https://official.example/about', 'quote': 'Headquartered in the US',
                    'checkedAt': '2026-09-19T10:00:00+08:00'}
        row['fieldSources']['country'] = [research]
        row['brandProfiles'] = {'AIHOT品牌': entity(self.a)}
        row['reviewMergedRecords'] = {'AIHOT旧名': entity(self.a)}
        before = copy.deepcopy(row)
        result = migration.clean_entity(row, self.provenance, [], self.checked)
        self.assertEqual(result['business'], 'Manus业务')
        self.assertEqual(result['country'], '美国')
        self.assertEqual(result['fieldSources']['country'], [research])
        self.assertEqual(result['product_names'], ['Manus产品'])
        self.assertEqual([a['id'] for a in result['sourceArticles']], ['manus:m'])
        self.assertEqual(result['brandProfiles'], {})
        self.assertEqual(result['reviewMergedRecords'], {})
        self.assertEqual(result['latestReportAt'], self.m['publishedAt'])
        self.assertEqual(result['profileUpdatedAt'], self.checked)
        self.assertEqual(row, before)

    def test_aihot_only_entity_removed_even_with_independent_research(self):
        row = entity(self.a)
        row['fieldSources']['country'] = [{'value': '美国', 'articleId': 'research:x',
            'origin': 'research', 'quote': 'US', 'checkedAt': self.checked, 'url': 'https://official.example'}]
        self.assertIsNone(migration.clean_entity(row, self.provenance, [], self.checked))

    def test_reviewed_null_not_resurrected_and_relabelled_aihot_research_removed(self):
        row = entity(self.a, self.m)
        row['business'] = None
        row['country'] = '美国'
        row['fieldSources']['country'] = [evidence(self.a, '美国', origin='research', quote='美国', checkedAt=self.checked)]
        result = migration.clean_entity(row, self.provenance, [], self.checked)
        self.assertIsNone(result['business'])
        self.assertIsNone(result['country'])

    def test_exact_shared_url_can_remap_aihot_id_to_existing_manus_evidence(self):
        a = {**self.a, 'url': self.m['url']}
        p = migration.Provenance([{'items': [a, self.m]}])
        result = p.article(a)
        self.assertEqual(result['id'], self.m['id'])
        self.assertEqual(result['collector'], 'manus')
        mixed = {**a, 'url': 'https://unknown.example/story', 'sourceRefs': [{'collector': 'manus'}]}
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            migration.Provenance([{'items': [mixed]}]).article(mixed)

    def test_tencent_alias_must_not_collapse_conflicting_or_credential_urls(self):
        url = 'https://news.qq.com/rain/a/20260922A0123400'
        self.assertEqual(migration.url_key(url), migration.url_key(url + '?id=20260922A0123400&app=news'))
        for invalid in [url + '?id=20260922A0999900',
                        url.replace('news.qq.com', 'user@news.qq.com'),
                        url.replace('news.qq.com', 'news.qq.com:443')]:
            a = {**self.a, 'url': invalid}
            m = {**self.m, 'url': url}
            self.assertIsNone(migration.Provenance([{'items': [a, m]}]).article(a))

    def test_mixed_funding_retains_only_supported_current_values(self):
        row = {'id': 'fund:test', 'company_name': '保留公司', 'sourceArticles': [self.a, self.m],
               'business': 'Manus业务', 'country': '猜测国家', 'total_funding': '旧金额',
               'dims': {'所属行业': '其他', '公司类型': '其他', '国家/地区': '其他'}}
        cache = {'1:5:model:manus:m:hash': {'status': 'complete', 'companies': [{'company_name': '保留公司', 'business': 'Manus业务'}]}}
        out = migration.clean_funding({'companies': [row]}, self.provenance, cache, [], [], self.checked)
        self.assertEqual(out['companies'][0]['business'], 'Manus业务')
        self.assertIsNone(out['companies'][0]['country'])
        self.assertIsNone(out['companies'][0]['total_funding'])
        self.assertEqual(out['stats']['modelCalls'], 0)

    def test_review_reports_do_not_expose_removed_entities_or_claim_new_calls(self):
        report = {'checkedAt': '2026-09-19T10:00:00+08:00', 'modelRequests': 73,
                  'records': [{'id': 'company:test', 'name': '保留公司'}, {'id': 'company:removed', 'name': '删除公司'}]}
        result = migration.clean_public_review(report, {'companies': [entity(self.a, self.m)]}, self.checked)
        self.assertEqual(len(result['records']), 1)
        self.assertNotIn('modelRequests', result)
        self.assertEqual(result['checkedAt'], report['checkedAt'])
        self.assertEqual(result['sourceMigration']['newModelCalls'], 0)

    def test_old_aihot_navigation_is_removed(self):
        value = {'dailyHistory': [{'date': '2026-09-21', 'url': 'https://aihot.news/daily/2026-09-21'}],
                 'qualityReview': {'classifications': {'aihot:a': {'category': 'general'}}}}
        result = migration.filter_news(value, self.provenance)
        self.assertEqual(result['dailyHistory'], [])
        self.assertEqual(result['qualityReview']['classifications'], {})

    def fixture(self, root):
        source = root / 'work/source'
        snapshot = {'all': {'items': [self.a, self.m]}, 'garenaSelected': {'items': [self.a, self.m]},
            'newsSelectionVersion': 1, 'dailyReports': {'old': {'attribution': {'name': 'AIHOT'}, 'sections': []}},
            'collectionStatus': {'sources': [{'collector': 'aihot', 'name': 'AIHOT'}, {'collector': 'manus', 'name': '测试媒体'}]}}
        overview = {'schemaVersion': 1, 'generatedAt': self.checked, 'companies': [entity(self.a, self.m)],
            'stats': {'articlesProcessed': 2, 'modelCalls': 2}, 'knownLinkResearchState': {'reservation': {'checkedAt': self.checked}}}
        for relative, value in {'web/public/snapshot.json': snapshot,
            'data/company-overview/current.json': overview, 'web/public/company-overview.json': overview,
            'data/funding/current.json': {'schemaVersion': 1, 'companies': [], 'stats': {'modelCalls': 7}},
            'inputs/processed.json': {'items': [self.a, self.m], 'allArticles': [self.a, self.m]},
            'data/manus/current.json': {'items': [self.m]},
            'data/archive/2026-09-21.json': {'items': [self.a, self.m]},
            'data/cache/news_enrichment.json': {'paidOldResult': 'unchanged'},
            'data/company-overview/extraction_cache.json': {'aihot:cache': 'unchanged'}}.items():
            migration.write(source / relative, value)
        return source

    def test_workspace_isolated_counts_caches_and_reservations_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self.fixture(root); output = root / 'work/output'
            baseline = migration.fingerprint(source)
            report = migration.migrate_workspace(source, output, root=root, checked_at=self.checked)
            self.assertEqual(migration.fingerprint(source), baseline)
            self.assertTrue(report['inputUnchanged'])
            self.assertFalse(report['readyForPublish'])
            self.assertEqual(report['news']['afterLibrary'], 1)
            self.assertEqual(report['news']['afterSelected'], 1)
            self.assertEqual(report['originalStats']['data/company-overview/current.json']['modelCalls'], 2)
            overview = migration.read(output / 'data/company-overview/current.json')
            self.assertEqual(overview['stats']['modelCalls'], 0)
            self.assertEqual(overview['stats']['articlesProcessed'], 1)
            self.assertEqual(overview['knownLinkResearchState'], {'reservation': {'checkedAt': self.checked}})
            self.assertEqual((output / 'data/cache/news_enrichment.json').read_bytes(), (source / 'data/cache/news_enrichment.json').read_bytes())
            self.assertEqual(migration.read(output / 'web/public/snapshot.json')['dailyReports'], {})
            with self.assertRaises(ValueError):
                migration.migrate_workspace(source, output, root=root)
            with self.assertRaises(ValueError):
                migration.migrate_workspace(source, root / 'data', root=root)


if __name__ == '__main__':
    unittest.main()
