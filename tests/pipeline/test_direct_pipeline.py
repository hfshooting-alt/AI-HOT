"""Direct collection must preserve source/time proof and the two news pools."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import news_pipeline
import screen_news
import enrich_news
from automation.runner import plan, DIRECT_STAGES
from direct_source.collector import load, validate_result
from direct_source.transport import allowed
from direct_source.reviews import apply as review_items
from manus_source.config import load_sources
from manus_source.window import ten_am_window, matching_item


class DirectPipeline(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'NEWS_COLLECTION_END': '2026-09-23T15:00:00+08:00'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.groups = load_sources(ROOT / 'config/manus_sources.json')
        self.window = ten_am_window('2026-09-23')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.sources = [{'source': s, 'status': 'complete', 'items': [], 'coverage': {}}
                        for sources in self.groups.values() for s in sources]
        self.item = {'title': '具体文章', 'url': 'https://news.qq.com/rain/a/20260923A06QC800',
            'publishedAt': '2026-09-23T12:30:03+08:00', 'publishedPrecision': 'datetime',
            'content_text': '可核实正文事实。' * 30,
            'validation': {'titleMatched': True, 'sourceMatched': True, 'publicationTimeVerified': True},
            'timeEvidence': {'kind': 'absolute', 'field': 'article:published_time',
                'originalText': '2026-09-23 12:30:03', 'normalizedAt': '2026-09-23T12:30:03+08:00',
                'observedAt': '2026-09-23T15:00:10+08:00'}}
        self.sources[0]['items'] = [self.item]

    def write(self):
        path = self.workspace / 'collection.json'
        path.write_text(json.dumps({'schemaVersion': 1, 'collector': 'direct_site',
            'collectionWindow': self.window, 'sources': self.sources}), encoding='utf-8')
        return path

    def test_absolute_evidence_and_exclusive_upper_bound(self):
        self.assertTrue(matching_item(self.window, self.item))
        invalid = copy.deepcopy(self.item)
        invalid['timeEvidence']['normalizedAt'] = self.window['end']
        self.assertFalse(matching_item(self.window, invalid))
        invalid['publishedAt'] = self.window['end']
        self.assertFalse(matching_item(self.window, invalid))
        invalid['timeEvidence']['kind'] = 'unverified'
        self.assertFalse(matching_item(self.window, invalid))

    def test_missing_identity_and_missing_source_fail_closed(self):
        self.sources[0]['items'][0]['validation']['sourceMatched'] = False
        with self.assertRaises(ValueError):
            load(self.write(), '2026-09-23', self.groups)
        self.sources.pop()
        with self.assertRaises(ValueError):
            load(self.write(), '2026-09-23', self.groups)

    def test_all_articles_classified_without_entering_selected(self):
        no_body = copy.deepcopy(self.item)
        no_body.update(title='已核实但暂无正文', url='https://news.qq.com/rain/a/20260923A0000100', content_text='')
        self.sources[0]['items'].append(no_body)

        def screen(items, *args, **kwargs):
            return ({screen_news.item_key(i): {'status': 'complete', 'relevant': False, 'reason': '普通新闻'} for i in items}, {'irrelevant': len(items)})

        def enrich(items, *args, **kwargs):
            return {enrich_news.enrich_item_key(i): {'enrichmentStatus': 'complete', 'summary': '原文事实摘要。' * 20,
                'classification': {'category': 'general', 'tags': {}, 'autoFallback': False, 'autoFilled': []}} for i in items}

        result = news_pipeline.process('2026-09-23', self.workspace, self.workspace,
            screen_fn=screen, enrich_fn=enrich, direct_input=self.write())
        self.assertEqual(result['sourceMode'], 'direct-only')
        self.assertEqual(result['items'], [])
        self.assertEqual(len(result['allArticles']), 2)
        by_title = {i['title']: i for i in result['allArticles']}
        self.assertEqual(by_title['具体文章']['classificationStatus'], 'complete')
        self.assertEqual(by_title['具体文章']['garenaSelection']['status'], 'not_selected')
        self.assertEqual(by_title['已核实但暂无正文']['contentStatus'], 'awaiting_body')
        self.assertTrue(all(i['collector'] == 'direct_site' and i['id'].startswith('direct:') for i in result['allArticles']))
        self.assertNotIn('content_text', json.dumps(result))
        feed = json.loads((self.workspace / 'data/manus/current.json').read_text(encoding='utf-8'))
        self.assertEqual((feed['schemaVersion'], feed['collector']), (3, 'direct_site'))

    def test_direct_plan_never_submits_manus_or_collects_aihot(self):
        commands = plan(ROOT, self.workspace, '2026-09-23', ten_am=True, combined=True, source_mode='direct-only')
        active = '\n'.join(' '.join(commands[stage]) for stage in DIRECT_STAGES)
        self.assertNotIn('manus_source/runner.py', active)
        self.assertNotIn('--discover-company', active)
        self.assertIn('--direct-input', active)
        self.assertIn('--evidence-json', ' '.join(commands['funding']))

    def test_transport_rejects_unapproved_targets(self):
        for url in ('http://news.qq.com/a', 'https://127.0.0.1/a', 'https://news.qq.com@evil.test/a', 'https://news.qq.com:444/a'):
            with self.assertRaises(ValueError):
                allowed(url)

    def test_editorial_quarantine_requires_exact_original_body(self):
        import hashlib
        source = self.sources[0]['source']
        rules = {'schemaVersion': 1, 'reviews': [{'reviewedAt': '2026-09-23',
            'action': 'withhold_body', 'source': source['account_name'], 'url': self.item['url'],
            'title': self.item['title'], 'contentSha256': hashlib.sha256(self.item['content_text'].encode()).hexdigest(),
            'reason': 'reviewed title/body mismatch'}]}
        self.assertEqual(review_items(source, [self.item], rules)[0]['content_text'], '')
        self.assertTrue(self.item['content_text'])
        repaired = {**self.item, 'content_text': '修复后的正确正文' * 30}
        self.assertEqual(review_items(source, [repaired], rules)[0]['content_text'], repaired['content_text'])


if __name__ == '__main__':
    unittest.main()
