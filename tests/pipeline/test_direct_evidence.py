"""Source provenance and cache-only financing recovery for direct-site batches."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

import build_snapshot
import tag_news
from automation import recovery
from automation.publish import ALLOWED, save
from automation.runner import tree_digest, validate_news_pools
from company_index.extraction import cache_key as company_cache_key
from direct_source.transport import Transport
from funding.extraction import article_cache_key, extract_articles
from funding.inputs import load_articles


class DirectEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.window = {'start': '2026-09-22T15:00:00+08:00',
                       'end': '2026-09-23T15:00:00+08:00', 'timezone': 'Asia/Shanghai'}
        self.env = patch.dict(os.environ, {'LLM_MODEL': 'offline-direct-evidence',
            'LLM_API_BASE': '', 'NEWS_COLLECTION_END': self.window['end']})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tx = tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        taxonomy = patch.object(build_snapshot, 'TAG_TAXONOMY', self.tx)
        taxonomy.start()
        self.addCleanup(taxonomy.stop)
        self.body = 'Direct Demo Labs announces a funding round. The original article identifies the investor and amount. ' * 3
        financing = next(category for category in self.tx['categories'] if category['id'] == 'financing')
        cls = {'category': 'financing', 'autoFallback': False, 'autoFilled': [],
               'tags': {dim: self.tx['dimensions'][dim]['fallbackValueId']
                        for dim in financing['dims']}}
        self.item = {'id': 'direct:evidence001', 'title': '可追溯融资报道',
            'url': 'https://example.com/news/funding', 'summary': '模型生成摘要不应替代原文。',
            'source': '官网资讯：测试媒体', 'mpName': '测试媒体', 'sourceType': 'media',
            'collector': 'direct_site', 'sourceChannel': 'publisher_site', 'sourcePlatform': 'Official Test',
            'publishedAt': '2026-09-23T12:00:00+08:00', 'publishedPrecision': 'datetime',
            'enrichmentStatus': 'complete', 'contentSha256': hashlib.sha256(self.body.encode()).hexdigest(),
            'classification': cls, 'garenaSelection': {'status': 'selected'},
            'sourceRefs': [{'collector': 'direct_site', 'source': '测试媒体',
                           'url': 'https://example.com/news/funding', 'publishedAt': '2026-09-23T12:00:00+08:00'}],
            'timeEvidence': {'kind': 'absolute', 'field': 'article:published_time',
                'originalText': '2026-09-23 12:00:00', 'normalizedAt': '2026-09-23T12:00:00+08:00',
                'observedAt': '2026-09-23T15:00:10+08:00'}}
        self.status = {'collectionWindow': self.window, 'degraded': False,
            'sources': [{'name': '测试媒体', 'collector': 'direct_site', 'status': 'complete'}],
            'candidateArticles': 1, 'publishedArticles': 1, 'articleLibraryCount': 1,
            'excludedArticles': 0, 'quarantinedArticles': 0, 'quarantined': []}
        self.processed = {'sourceMode': 'direct-only', 'collectionWindow': self.window,
            'collectionStatus': self.status, 'items': [self.item], 'allArticles': [self.item]}
        self.snapshot = {'sourceMode': 'direct-only', 'collectionWindow': self.window,
            'collectionStatus': self.status, 'daily': {'sections': []}, 'weekly': {'sections': []},
            'history': [], 'weeklyNav': [], 'generatedAt': self.window['end']}
        build_snapshot.apply_article_pools(self.snapshot, self.processed,
                                          build_snapshot.datetime.fromisoformat(self.window['end']))
        self.evidence = {'id': self.item['id'], 'url': self.item['url'], 'content_text': self.body}

    def write_inputs(self, workspace):
        save(workspace / 'web/public/snapshot.json', self.snapshot)
        save(workspace / 'inputs/company-evidence.json', [self.evidence])
        save(workspace / 'inputs/processed.json', self.processed)
        save(workspace / 'data/manus/current.json', {'schemaVersion': 3, 'collector': 'direct_site',
            'targetDate': '2026-09-23', 'generatedAt': self.window['end'], 'ok': True, 'degraded': False,
            'collectionWindow': self.window, 'collectionStatus': self.status, 'items': [self.item],
            'stats': {'configuredAccounts': 1, 'completeAccounts': 1, 'failedAccounts': 0,
                      'discoveredArticles': 1, 'publishedArticles': 1, 'fallbackArticles': 0}})

    def load_funding(self, workspace, raw=None):
        return load_articles(workspace / 'web/public/snapshot.json', workspace / 'data/manus/current.json',
            raw or workspace / 'no-manus-raw', self.tx, evidence_path=workspace / 'inputs/company-evidence.json')

    def test_unchanged_provenance_passes_without_mutating_either_pool(self):
        before = copy.deepcopy((self.snapshot, self.processed))
        selected, library = validate_news_pools(self.snapshot, self.processed, self.tx)
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(library), 1)
        self.assertEqual((self.snapshot, self.processed), before)

    def test_mutating_both_visible_pools_cannot_disguise_source_provenance(self):
        for field, value in {'collector': 'manus', 'sourcePlatform': 'Unrelated Platform',
                             'sourceChannel': 'wechat_original', 'sourceRefs': [], 'timeEvidence': None}.items():
            with self.subTest(field=field):
                bad = copy.deepcopy(self.snapshot)
                for pool in ('all', 'garenaSelected'):
                    bad[pool]['items'][0][field] = value
                with self.assertRaisesRegex(ValueError, '来源证据'):
                    validate_news_pools(bad, self.processed, self.tx)

    def test_source_mode_must_match_current_collector(self):
        with self.assertRaisesRegex(ValueError, '采集模式'):
            validate_news_pools({**self.snapshot, 'sourceMode': 'manus-only'}, self.processed, self.tx)

    def test_bound_body_overrides_summary_and_same_title_historical_content(self):
        self.write_inputs(self.root)
        raw = self.root / 'raw-history'
        save(raw / '2026-09-20/raw/content-batch-01.json', {'articles': [{
            'title': self.item['title'], 'article_url': 'https://example.com/other-article',
            'content_text': 'Unrelated same-title body that must never be used.' * 5}]})
        articles = self.load_funding(self.root, raw)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]['id'], self.item['id'])
        self.assertEqual(articles[0]['url'], self.item['url'])
        self.assertEqual(articles[0]['content_text'], self.body)
        self.assertEqual(articles[0]['evidenceKind'], 'article_body')

    def test_wrong_url_or_id_fails_instead_of_falling_back_to_summary(self):
        self.write_inputs(self.root)
        for change in ({'url': 'https://example.com/wrong'}, {'id': 'direct:wrong'}):
            with self.subTest(change=change):
                save(self.root / 'inputs/company-evidence.json', [{**self.evidence, **change}])
                with self.assertRaisesRegex(ValueError, 'ID and URL'):
                    self.load_funding(self.root)

    def test_same_restored_body_reuses_success_cache_without_request(self):
        self.write_inputs(self.root)
        original = self.load_funding(self.root)[0]
        key = article_cache_key(self.tx, original)
        restored = self.root / 'restored'
        self.write_inputs(restored)
        loaded = self.load_funding(restored)[0]
        self.assertEqual(article_cache_key(self.tx, loaded), key)
        self.assertNotEqual(article_cache_key(self.tx, {**loaded, 'content_text': self.item['summary']}), key)
        cache_path = restored / 'data/funding/extraction_cache.json'
        save(cache_path, {key: {'status': 'complete', 'companies': [], 'modelAttempted': True}})
        cache_before = cache_path.read_bytes()
        model = Mock(side_effect=AssertionError('cache recovery cannot call a model'))
        with contextlib.redirect_stdout(io.StringIO()):
            result = extract_articles(self.tx, [loaded], cache_path, llm_fn=model)
        model.assert_not_called()
        self.assertTrue(result[loaded['id']]['cacheHit'])
        self.assertFalse(result[loaded['id']]['modelAttempted'])
        self.assertEqual(cache_path.read_bytes(), cache_before)

    def test_direct_rebuild_reuses_body_cache_and_preserves_original_state(self):
        save(self.root / 'config/taxonomy.json', self.tx)
        manifest_root = self.root / 'work/recovered/synthetic-bundle'
        save(manifest_root / 'manifest.json', {'version': 1, 'files': {}})
        source = manifest_root / 'work/runs/2026-09-23/ten-am' / ('a' * 32)
        workspace = source / 'workspace'
        for rel in ALLOWED:
            (workspace / rel).mkdir(parents=True, exist_ok=True)
        self.write_inputs(workspace)
        save(workspace / 'data/company-overview/current.json', {'companies': []})
        save(workspace / 'data/company-overview/extraction_cache.json', {
            company_cache_key(self.tx, {**self.item, 'content_text': self.body}):
                {'status': 'complete', 'companies': []}})
        key = article_cache_key(self.tx, self.load_funding(workspace)[0])
        save(workspace / 'data/funding/extraction_cache.json', {
            key: {'status': 'complete', 'companies': []}})
        state = {'date': '2026-09-23', 'fingerprint': 'saved-direct-run', 'sourceMode': 'direct-only',
            'collectionWindow': self.window, 'modelContext': {'LLM_MODEL': 'offline-direct-evidence'},
            'recoveryBaseline': {rel: tree_digest(self.root / rel, portable=True) for rel in ALLOWED},
            'stages': {'news': {'status': 'success'}, 'snapshot': {'status': 'success'},
                       'overview': {'status': 'failed'}}}
        save(source / 'state.json', state)
        before = (source / 'state.json').read_bytes()
        with patch.object(recovery, 'deny_model', side_effect=AssertionError('no model during recovery')) as model, \
                contextlib.redirect_stdout(io.StringIO()):
            report = recovery.rebuild(self.root, source)
        model.assert_not_called()
        self.assertEqual(report['status'], 'review_ready')
        reviewed = Path(report['reviewDirectory']) / 'workspace'
        funding = json.loads((reviewed / 'data/funding/current.json').read_text(encoding='utf-8'))
        self.assertEqual(funding['stats']['articlesProcessed'], 1)
        self.assertEqual(funding['stats']['cacheHits'], 1)
        self.assertEqual(funding['stats']['modelCalls'], 0)
        self.assertEqual(article_cache_key(self.tx, self.load_funding(reviewed)[0]), key)
        self.assertEqual((source / 'state.json').read_bytes(), before)
        self.assertFalse((self.root / 'web/public/snapshot.json').exists())

    def test_recovery_body_allowlist_is_limited_to_direct_http_receipts(self):
        run_id, source_id = 'a' * 32, 'b' * 12
        approved = f'work/runs/2026-09-23/ten-am/{run_id}/workspace/inputs/direct/{source_id}/http/0001.body'
        self.assertTrue(recovery.allowed(approved))
        rejected = [
            'work/runs/arbitrary.body', 'work/manus/raw/0001.body',
            'work/company-web-research/0001.body', 'work/company-research-budget/0001.body',
            approved.replace('/inputs/direct/', '/inputs/other/'),
            approved.replace('/workspace/inputs/', '/backup/inputs/'),
            approved.replace(run_id, 'g' * 32), approved.replace(run_id, 'a' * 31),
            approved.replace(source_id, 'b' * 13), approved.replace(source_id, 'g' * 12),
            approved.replace('0001.body', 'request.body'), approved.replace('0001.body', '1.body'),
            approved.replace('/http/', '/http/extra/'),
            approved.replace('/http/', '/http/../http/'),
            approved.replace('/http/', '/./http/'),
            approved.replace('/http/', '/%2e%2e/http/'),
            '/' + approved, '../' + approved, approved.replace('/', '\\'),
        ]
        for name in rejected:
            with self.subTest(name=name):
                self.assertFalse(recovery.allowed(name))

    def test_access_denial_stops_later_http_but_keeps_original_receipt(self):
        first_url = 'https://news.qq.com/rain/a/20260923A0000100'
        later_url = 'https://news.qq.com/rain/a/20260923A0000200'
        body = b'Anonymous access denied'
        for status in (403, 429):
            with self.subTest(status=status):
                opener = Mock()
                opener.open.side_effect = HTTPError(first_url, status, 'Denied', {}, io.BytesIO(body))
                directory = self.root / f'http-{status}'
                with patch('direct_source.transport.urllib.request.build_opener', return_value=opener):
                    transport = Transport(directory)
                with self.assertRaisesRegex(ValueError, f'HTTP {status}'):
                    transport(first_url)
                receipt_path = directory / '0001.json'
                receipt_before = receipt_path.read_bytes()
                receipt = json.loads(receipt_before)
                self.assertEqual(receipt['url'], first_url)
                self.assertEqual(receipt['httpStatus'], status)
                self.assertEqual(receipt['sha256'], hashlib.sha256(body).hexdigest())
                self.assertEqual((directory / '0001.body').read_bytes(), body)
                for url in (later_url, first_url):
                    with self.assertRaisesRegex(ValueError, 'no further requests'):
                        transport(url)
                self.assertEqual(opener.open.call_count, 1)
                self.assertEqual(transport.count, 1)
                self.assertEqual(receipt_path.read_bytes(), receipt_before)
                self.assertFalse((directory / '0002.json').exists())
                self.assertFalse((directory / '0002.body').exists())


if __name__ == '__main__':
    unittest.main()
