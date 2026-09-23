"""Direct-site publication preserves collector identity without reviving AIHOT."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

import build_snapshot
import enrich_news
import news_pipeline
import screen_news
import tag_news
from automation.runner import validate_news_pools
from company_index.identity import active_article_fact, apply_reviewed_research
from manus_source import contracts

TAXONOMY = str(ROOT / 'config/taxonomy.json')


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls.fromisoformat('2026-09-23T18:01:00+08:00')
        return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)


def direct_feed():
    feed = json.loads((ROOT / 'tests/fixtures/manus/current.json').read_text(encoding='utf-8'))
    item = feed['items'][0]
    item.update(id='direct:001', collector='direct_site', source='测试媒体官网',
                sourceType='direct', sourceChannel='publisher_site', sourcePlatform='Official Test',
                mpName='测试媒体', url='https://example.com/news/001',
                publishedAt='2026-09-23T12:00:00+08:00', publishedPrecision='datetime')
    feed.update(schemaVersion=3, collector='direct_site', targetDate='2026-09-23', items=[item],
                stats={'configuredAccounts': 1, 'completeAccounts': 1, 'failedAccounts': 0,
                       'discoveredArticles': 1, 'publishedArticles': 1, 'fallbackArticles': 0})
    return feed


class DirectPublication(unittest.TestCase):
    def test_full_direct_time_proof_projects_identically_into_both_public_pools(self):
        end = '2026-09-23T18:00:00+08:00'
        window = {'start': '2026-09-22T18:00:00+08:00', 'end': end, 'timezone': 'Asia/Shanghai'}
        proof = {'field': 'article:published_time', 'originalText': '2026-09-23 12:00:00',
            'observedAt': end, 'normalizedAt': '2026-09-23T12:00:00+08:00',
            'precision': 'second', 'kind': 'absolute', 'url': 'https://example.com/news/001',
            'htmlSha256': 'a' * 64, 'originalPlatformPublication': True,
            'earliestGlobalPublicationVerified': False}
        article = {'account_name': '测试媒体', 'source_platform': 'Official Test',
            'title': '具体文章', 'article_url': proof['url'], 'published_at': proof['normalizedAt'],
            'published_date': '2026-09-23', 'publishedPrecision': 'datetime',
            'timeEvidence': proof, 'collector': 'direct_site', 'content_text': '原文可核实事实。' * 30,
            'extraction_status': 'complete'}
        original = copy.deepcopy(article)
        discoveries = {group: {'collectionWindow': window, 'source_audits': [], 'articles': []}
                       for group in news_pipeline.manus.GROUPS}
        group = news_pipeline.manus.GROUPS[0]
        discoveries[group] = {'collectionWindow': window,
            'source_audits': [{'account_name': '测试媒体', 'source_status': 'complete', 'article_count': 1}],
            'articles': [article]}
        audits = [{'name': '测试媒体', 'collector': 'direct_site', 'status': 'complete',
            'discoveredArticles': 1, 'usableArticles': 1, 'articleLibraryCount': 1}]

        def screen(items, *args, **kwargs):
            return ({screen_news.item_key(i): {'status': 'complete', 'relevant': True}
                     for i in items}, {})

        def enrich(items, *args, **kwargs):
            return {enrich_news.enrich_item_key(i): {'enrichmentStatus': 'complete',
                'summary': '可核实事实摘要。' * 20,
                'classification': {'category': 'general', 'tags': {}, 'autoFallback': False,
                                   'autoFilled': []}} for i in items}

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'NEWS_COLLECTION_END': end}), \
                patch('direct_source.collector.load', return_value=(discoveries, audits, [article])), \
                patch.object(build_snapshot, 'TAG_TAXONOMY', tag_news.load_taxonomy(TAXONOMY)):
            workspace = Path(directory)
            processed = news_pipeline.process('2026-09-23', workspace, workspace,
                screen_fn=screen, enrich_fn=enrich, direct_input=workspace / 'unused-collection.json')
            public_proof = {key: proof[key] for key in
                ('originalText', 'observedAt', 'kind', 'field', 'normalizedAt')}
            self.assertEqual(processed['items'][0]['timeEvidence'], public_proof)
            self.assertEqual(processed['allArticles'][0]['timeEvidence'], public_proof)
            snapshot = {'sourceMode': 'direct-only'}
            build_snapshot.apply_article_pools(snapshot, processed, datetime.fromisoformat(end))
            validate_news_pools(snapshot, processed, build_snapshot.TAG_TAXONOMY)
            for pool in ('all', 'garenaSelected'):
                self.assertEqual(snapshot[pool]['items'][0]['timeEvidence'], public_proof)
            self.assertEqual(article, original)
            self.assertEqual(discoveries[group]['articles'][0]['timeEvidence'], proof)

    def test_schema_three_preserves_direct_identity_and_legacy_feed(self):
        feed = direct_feed()
        before = copy.deepcopy(feed)
        contracts.validate_feed(feed, TAXONOMY)
        self.assertEqual(feed, before)
        old = json.loads((ROOT / 'tests/fixtures/manus/current.json').read_text(encoding='utf-8'))
        contracts.validate_feed(old, TAXONOMY)
        old['schemaVersion'] = 2
        for item in old['items']:
            item['sourceChannel'] = 'tencent_syndication'
        contracts.validate_feed(old, TAXONOMY)

    def test_old_schema_cannot_carry_direct_site(self):
        for version in (1, 2):
            with self.subTest(version=version):
                feed = direct_feed()
                feed['schemaVersion'] = version
                with self.assertRaises(contracts.ContractError):
                    contracts.validate_feed(feed, TAXONOMY)

    def test_identity_mismatch_aihot_and_unidentified_platform_rejected(self):
        for changes in ({'id': 'manus:001'}, {'id': 'aihot:001'}, {'collector': 'manus'},
                        {'collector': 'aihot'}, {'sourcePlatform': ''}, {'sourceChannel': 'unknown'}):
            with self.subTest(changes=changes):
                feed = direct_feed()
                feed['items'][0].update(changes)
                with self.assertRaises(contracts.ContractError):
                    contracts.validate_feed(feed, TAXONOMY)
        feed = direct_feed()
        feed['collector'] = 'aihot'
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(feed, TAXONOMY)

    def test_existing_body_and_classification_gates_remain(self):
        for changes in ({'content_text': '不得公开全文'}, {'classification': {'category': 'invalid'}}):
            with self.subTest(changes=changes):
                feed = direct_feed()
                feed['items'][0].update(changes)
                with self.assertRaises(contracts.ContractError):
                    contracts.validate_feed(feed, TAXONOMY)

    def test_prepared_source_mode_checks_both_pools_even_if_selected_empty(self):
        direct = direct_feed()['items'][0]
        prepared = {'sourceMode': 'direct-only', 'items': [], 'allArticles': [direct]}
        self.assertEqual(build_snapshot.prepared_source_mode(prepared), 'direct-only')
        self.assertEqual(build_snapshot.prepared_source_mode({**prepared, 'allArticles': []}), 'direct-only')
        for bad in ({**direct, 'id': 'manus:001'}, {**direct, 'collector': 'aihot'},
                    {**direct, 'collector': 'manus'}, {**direct, 'sourceChannel': None}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    build_snapshot.prepared_source_mode({**prepared, 'allArticles': [bad]})
        with self.assertRaises(ValueError):
            build_snapshot.prepared_source_mode({**prepared, 'sourceMode': 'manus-only'})
        with self.assertRaises(ValueError):
            build_snapshot.prepared_source_mode({**prepared, 'items': [
                {**direct, 'id': 'manus:002', 'collector': 'manus'}]})

    def test_public_pools_keep_source_fields_without_body(self):
        item = {**direct_feed()['items'][0], 'content_text': '私有正文',
                'garenaSelection': {'status': 'selected'}}
        data = {}
        build_snapshot.apply_article_pools(data, {'items': [item], 'allArticles': [item]},
                                          build_snapshot.datetime.now(build_snapshot.BJ))
        for pool in ('all', 'garenaSelected'):
            public = data[pool]['items'][0]
            for key in ('id', 'collector', 'source', 'sourceType', 'sourceChannel', 'sourcePlatform'):
                self.assertEqual(public[key], item[key])
            self.assertNotIn('content_text', public)
        self.assertEqual(build_snapshot.archive_key({**item, 'sourceType': 'wechat'}), 'id:direct:001')

    def test_snapshot_cli_direct_empty_selection_never_backfills_history(self):
        end = '2026-09-23T18:00:00+08:00'
        window = {'start': '2026-09-22T18:00:00+08:00', 'end': end, 'timezone': 'Asia/Shanghai'}
        item = {**direct_feed()['items'][0], 'garenaSelection': {'status': 'not_selected'}}
        prepared = {'sourceMode': 'direct-only', 'collectionWindow': window, 'items': [],
                    'allArticles': [item], 'collectionStatus': {'degraded': False,
                    'sources': [{'collector': 'direct_site', 'status': 'complete'}]}}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            archive = target / 'archive'
            archive.mkdir()
            historical = {**item, 'id': 'manus:history', 'collector': 'manus',
                          'publishedAt': '2026-09-21T12:00:00+08:00'}
            history_file = archive / '2026-09-21.json'
            history_file.write_text(json.dumps({'date': '2026-09-21', 'finalized': False,
                                               'items': [historical]}), encoding='utf-8')
            input_path = target / 'processed.json'
            input_path.write_text(json.dumps(prepared), encoding='utf-8')
            args = ['snapshot', '--input-json', str(input_path), '--window-date', '2026-09-23',
                    '--out', str(target / 'index.html'), '--snapshot-json', str(target / 'snapshot.json'),
                    '--archive-dir', str(archive), '--history-dir', str(target / 'history'),
                    '--weekly-dir', str(target / 'weekly'), '--taxonomy', TAXONOMY, '--no-tags']
            for flag, name in [('template', 'index'), ('history-template', 'history'), ('weekly-template', 'weekly')]:
                args += ['--' + flag, str(ROOT / f'scripts/templates/{name}.template.html')]
            with patch.dict(os.environ, {'NEWS_COLLECTION_END': end}), patch.object(sys, 'argv', args), \
                 patch.object(build_snapshot, 'datetime', FrozenDatetime), \
                 patch.object(build_snapshot, 'fetch_items', side_effect=AssertionError('no upstream')), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_snapshot.main(), 0)
            snapshot = json.loads((target / 'snapshot.json').read_text(encoding='utf-8'))
            self.assertEqual(snapshot['sourceMode'], 'direct-only')
            self.assertEqual([row['id'] for row in snapshot['all']['items']], ['direct:001'])
            self.assertEqual(snapshot['garenaSelected']['items'], [])
            self.assertEqual(snapshot['all']['items'][0]['collector'], 'direct_site')
            self.assertTrue(any(row['id'] == 'manus:history' for row in
                                json.loads(history_file.read_text(encoding='utf-8'))['items']))

    def test_legacy_feed_path_reports_real_collector(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'current.json'
            path.write_text(json.dumps(direct_feed()), encoding='utf-8')
            rows, status = build_snapshot.load_manus_feed(str(path), TAXONOMY, max_stale_days=9999)
            self.assertEqual(rows[0]['id'], 'direct:001')
            self.assertEqual(status['collector'], 'direct_site')
            self.assertNotIn('Manus', status['note'])

    def test_reviewed_article_fact_requires_retained_exact_id_and_url(self):
        article = direct_feed()['items'][0]
        fact = {'articleId': article['id'], 'url': article['url'], 'origin': 'article',
                'field': 'business', 'value': '提供 AI 工具', 'title': article['title'],
                'publishedAt': article['publishedAt'], 'quote': '提供 AI 工具'}
        row = {'id': 'company:test', 'company_name': '测试公司', 'product_names': [],
               'fieldSources': {}, 'sourceArticles': [article], 'lastSeenAt': article['publishedAt']}
        before = copy.deepcopy(row)
        result = apply_reviewed_research([row], {'checkedAt': '2026-09-23T18:00:00+08:00',
            'records': [{'record_name': '测试公司', 'reviewed': True, 'facts': [fact]}]})
        self.assertEqual(row, before)
        self.assertEqual(result[0]['sourceArticles'], [article])
        self.assertEqual(result[0]['fieldSources']['business'][0]['articleId'], 'direct:001')
        self.assertFalse(active_article_fact({**fact, 'url': 'https://example.com/wrong'}, [row]))
        self.assertFalse(active_article_fact(fact, [{'sourceArticles': []}]))
        retired = {**fact, 'articleId': 'aihot:old'}
        self.assertFalse(active_article_fact(retired, [{'sourceArticles': [
            {'id': retired['articleId'], 'url': retired['url']}]}]))
        self.assertTrue(active_article_fact({'origin': 'research', 'articleId': 'research:official'}, []))


if __name__ == '__main__':
    unittest.main()
