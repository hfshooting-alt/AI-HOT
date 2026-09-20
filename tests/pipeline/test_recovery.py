import base64
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from automation import recovery, candidate
from automation.publish import ALLOWED, save
from company_index.extraction import cache_key
import tag_news

ROOT = Path(__file__).resolve().parents[2]
KEY = 'unit-test-recovery-secret-never-a-real-key'


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'work/runs/2026-09-18/ten-am' / ('a' * 32)
        self.workspace = self.run / 'workspace'
        self.bundle = self.root / 'work/checkpoint/recovery.bin'
        self.state = {'fingerprint': 'old-code-keep-unchanged', 'published': False,
                      'modelContext': {'LLM_MODEL': 'test-model'},
                      'stages': {'news': {'status': 'success'}, 'snapshot': {'status': 'success'},
                                 'overview': {'status': 'failed'}}}
        from automation.runner import tree_digest
        self.state['recoveryBaseline'] = {rel: tree_digest(self.root / rel, portable=True) for rel in ALLOWED}
        save(self.run / 'state.json', self.state)

    def test_encrypted_round_trip_excludes_environment_and_code(self):
        save(self.workspace / 'inputs/evidence.json', {'body': 'PRIVATE-ARTICLE-TEXT'})
        (self.workspace / '.env').write_text('PASSWORD=do-not-copy')
        (self.workspace / 'execute.py').write_text('raise SystemExit')
        (self.workspace / 'web/public').mkdir(parents=True)
        (self.workspace / 'web/public/logo.svg').write_text('<svg/>')
        recovery.pack(self.root, self.bundle, KEY)
        self.assertNotIn(b'PRIVATE-ARTICLE-TEXT', self.bundle.read_bytes())
        restored = recovery.unpack(self.root, self.bundle, KEY)
        files = list(restored.rglob('*'))
        self.assertFalse(any(p.name in ('.env', 'execute.py') for p in files))
        self.assertEqual(next(restored.glob('**/logo.svg')).read_text(), '<svg/>')
        state = next(restored.glob('work/runs/**/state.json'))
        self.assertEqual(json.loads(state.read_text()), self.state)
        self.assertEqual(json.loads(next(restored.glob('**/evidence.json')).read_text())['body'], 'PRIVATE-ARTICLE-TEXT')

    def test_wrong_key_tampering_and_missing_key_do_not_restore(self):
        recovery.pack(self.root, self.bundle, KEY)
        with self.assertRaises(ValueError):
            recovery.unpack(self.root, self.bundle, KEY + '-wrong')
        blob = bytearray(self.bundle.read_bytes()); blob[-10] ^= 1
        self.bundle.write_bytes(blob)
        with self.assertRaises(ValueError):
            recovery.unpack(self.root, self.bundle, KEY)
        self.assertFalse((self.root / 'work/recovered').exists())
        with self.assertRaises(ValueError):
            recovery.pack(self.root, self.bundle, '')

    def test_private_research_journal_results_and_attempts_restore_without_resetting_live_lease(self):
        budget = self.root / 'work/company-research-budget'
        save(budget / 'lease.json', {'owner': 'old-run:1'})
        save(budget / 'ledger.json', {'requests': 5, 'private': 'PRIVATE-RESEARCH-JOURNAL'})
        save(budget / 'results/result.json', {'facts': ['PRIVATE-SUCCESSFUL-PROPOSAL']})
        attempt_name = 'work/company-web-research/nested/' + 'a' * 64 + '.attempt'
        attempt = self.root / attempt_name
        attempt.parent.mkdir(parents=True)
        attempt.write_text('reserved', encoding='utf-8')
        stable_attempt_name = 'work/company-research-budget/model-cache/2026-09-20/' + 'c' * 64 + '.attempt'
        stable_attempt = self.root / stable_attempt_name
        stable_attempt.parent.mkdir(parents=True)
        stable_attempt.write_text('reserved before request', encoding='utf-8')
        (attempt.parent / 'arbitrary.attempt').write_text('not allowed', encoding='utf-8')
        (budget / ('b' * 64 + '.attempt')).write_text('not allowed', encoding='utf-8')
        recovery.pack(self.root, self.bundle, KEY)
        self.assertNotIn(b'PRIVATE-RESEARCH', self.bundle.read_bytes())
        self.assertNotIn(b'PRIVATE-SUCCESSFUL', self.bundle.read_bytes())
        # Unpack is isolated; old checkpoints cannot reset today's reservation.
        save(budget / 'lease.json', {'owner': 'current-run:1'})
        restored = recovery.unpack(self.root, self.bundle, KEY)
        recovered_budget = restored / 'work/company-research-budget'
        self.assertEqual(json.loads((budget / 'lease.json').read_text())['owner'], 'current-run:1')
        self.assertEqual(json.loads((recovered_budget / 'lease.json').read_text())['owner'], 'old-run:1')
        self.assertEqual(json.loads((recovered_budget / 'ledger.json').read_text())['requests'], 5)
        self.assertTrue((recovered_budget / 'results/result.json').exists())
        self.assertEqual((restored / attempt_name).read_text(), 'reserved')
        self.assertEqual((restored / stable_attempt_name).read_text(), 'reserved before request')
        self.assertFalse(any(p.name == 'arbitrary.attempt' for p in restored.rglob('*')))
        self.assertFalse((recovered_budget / ('b' * 64 + '.attempt')).exists())

    def test_attempt_exception_cannot_escape_private_research_tree(self):
        digest = 'a' * 64 + '.attempt'
        for name in ['work/runs/' + digest, 'work/company-web-research/../' + digest,
                     'work/company-web-research/.hidden/' + digest,
                     'work/company-research-budget/model-cache/arbitrary/' + digest,
                     'work/company-research-budget/model-cache/2026-09-20/nested/' + digest,
                     'work/company-web-research/' + ('g' * 64) + '.attempt',
                     'work/company-web-research/' + ('a' * 63) + '.attempt']:
            with self.subTest(name=name):
                self.assertFalse(recovery.allowed(name))

    def test_default_safe_model_failure_log_survives_encrypted_recovery(self):
        import llm_common
        import urllib.error
        error = urllib.error.HTTPError('https://example.com/private-token', 429,
            'PRIVATE-PROVIDER-BODY', {'Authorization': 'PRIVATE-HEADER'}, None)
        with patch.object(llm_common, '_PROJECT_ROOT', self.root), patch.dict(os.environ, {}, clear=True):
            llm_common.record_usage('offline-model', {'total_tokens': 10}, 'news_enrichment')
            llm_common.record_failure('offline-model', error, 'news_enrichment')
        original = (self.root / 'work/llm-failures.jsonl').read_bytes()
        self.assertNotIn(b'PRIVATE', original)
        self.assertNotIn(b'private-token', original)
        # Adding one operational log must not broaden recovery to arbitrary work files.
        (self.root / 'work/llm-debug.jsonl').write_text('PRIVATE-UNAPPROVED-LOG')
        recovery.pack(self.root, self.bundle, KEY)
        self.assertNotIn(original, self.bundle.read_bytes())
        restored = recovery.unpack(self.root, self.bundle, KEY)
        self.assertEqual((restored / 'work/llm-failures.jsonl').read_bytes(), original)
        self.assertTrue((restored / 'work/llm-usage.jsonl').exists())
        self.assertFalse((restored / 'work/llm-debug.jsonl').exists())
        diagnostic = json.loads(original)
        self.assertEqual(diagnostic['error']['category'], 'rate_limit')
        self.assertEqual(diagnostic['error']['httpStatus'], 429)

    def test_authenticated_archive_path_traversal_still_rejected(self):
        buf = io.BytesIO()
        path = 'work/runs/../../escape.json'
        import hashlib
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr(path, '{}')
            z.writestr('manifest.json', json.dumps({'version': 1, 'files': {path: hashlib.sha256(b'{}').hexdigest()}}))
        salt = os.urandom(16)
        self.bundle.parent.mkdir(parents=True)
        self.bundle.write_bytes(recovery.MAGIC + salt + recovery.cipher(KEY, salt).encrypt(buf.getvalue()))
        with self.assertRaises(ValueError):
            recovery.unpack(self.root, self.bundle, KEY)
        self.assertFalse((self.root / 'work/recovered').exists())

    def test_post_promotion_outputs_survive_git_push_failure(self):
        save(self.run / 'publication.json', {'status': 'committed', 'entries': [{'path': 'web/public'}]})
        save(self.root / 'web/public/snapshot.json', {'new': True})
        from automation.runner import tree_digest
        save(self.run / 'state.json', dict(self.state, publishedOutputs={
            'web/public': tree_digest(self.root / 'web/public')}))
        recovery.pack(self.root, self.bundle, KEY)
        restored = recovery.unpack(self.root, self.bundle, KEY)
        snapshots = list(restored.glob('work/runs/**/workspace/web/public/snapshot.json'))
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(json.loads(snapshots[0].read_text())['new'])

    def cached_fixture(self, cached=True):
        (self.root / 'config').mkdir()
        shutil.copyfile(ROOT / 'config/taxonomy.json', self.root / 'config/taxonomy.json')
        tx = tag_news.load_taxonomy(str(self.root / 'config/taxonomy.json'))
        for rel in ALLOWED:
            (self.workspace / rel).mkdir(parents=True, exist_ok=True)
        item = {'id': 'article', 'title': 'Named app launches', 'url': 'https://example.com/news',
                'summary': 'An application launched today.', 'publishedAt': '2026-09-17T12:00:00+08:00',
                'classification': {'cat': 'release', 'dims': []}}
        save(self.workspace / 'web/public/snapshot.json', {'all': {'items': [item]},
            'collectionStatus': {'present': True}, 'daily': {'sections': []}, 'weekly': {'sections': []}})
        save(self.workspace / 'data/manus/current.json', {'ok': True, 'items': []})
        evidence = dict(item, content_text='Exact collected evidence for named app.')
        save(self.workspace / 'inputs/company-evidence.json', [evidence])
        save(self.workspace / 'data/company-overview/current.json', {'companies': []})
        with patch.dict(os.environ, {'LLM_MODEL': 'test-model'}):
            key = cache_key(tx, evidence)
        save(self.workspace / 'data/company-overview/extraction_cache.json',
             {key: {'status': 'complete', 'companies': []}} if cached else {})
        recovery.pack(self.root, self.bundle, KEY)
        restored = recovery.unpack(self.root, self.bundle, KEY)
        return next(restored.glob('work/runs/**/state.json')).parent

    def test_cache_only_rebuild_preserves_origin_and_requires_review(self):
        source = self.cached_fixture()
        # Candidate consistency/publication gates have their own real validator
        # tests; this fixture isolates extraction/cache/encryption recovery.
        with patch.object(candidate, 'validate', return_value={'news': 1}), \
                patch.object(recovery, 'deny_model', side_effect=AssertionError('must not call model')) as model:
            report = recovery.rebuild(self.root, source)
        model.assert_not_called()
        self.assertEqual(report['paidCalls'], 0)
        self.assertEqual(report['status'], 'review_ready')
        self.assertFalse((self.root / 'web/public/snapshot.json').exists())
        self.assertEqual(json.loads((source / 'state.json').read_text()), self.state)
        self.assertTrue((Path(report['reviewDirectory']) / 'recovery-origin.json').exists())

    def test_rebuild_replays_unpublished_research_with_original_evidence_dates(self):
        import build_company_overview as overview
        from company_index.daily_research import enrich
        source = self.cached_fixture()
        w = source / 'workspace'
        manifest_root = next(p for p in source.parents if (p / 'manifest.json').exists())
        budget = manifest_root / 'work/company-research-budget'
        cache_path = w / 'data/company-overview/extraction_cache.json'
        cache = json.loads(cache_path.read_text())
        next(iter(cache.values()))['companies'] = [{'company_name': 'Replay Example Labs',
            'entity_type': 'company', 'aliases': [], 'product_names': []}]
        save(cache_path, cache)
        snapshot = json.loads((w / 'web/public/snapshot.json').read_text())
        snapshot['daily']['generatedAt'] = '2026-09-18T01:40:00Z'
        save(w / 'web/public/snapshot.json', snapshot)
        tx = tag_news.load_taxonomy(str(self.root / 'config/taxonomy.json'))
        original_time = '2026-09-18T09:45:00+08:00'
        with patch.dict(os.environ, {'LLM_MODEL': 'test-model', 'GITHUB_ACTIONS': ''}), \
                patch('company_index.daily_research.now_bj_iso', return_value=original_time):
            data = overview.build(w / 'web/public/snapshot.json', w / 'data/manus/current.json',
                manifest_root / 'work/manus/ten-am', w / 'data/company-overview/current.json',
                w / 'data/company-overview', tx, llm_fn=recovery.deny_model,
                generated_at='2026-09-18T09:40:00+08:00',
                evidence_path=w / 'inputs/company-evidence.json')
            enriched = enrich(data, tx, self.root / 'unused-old-cache', budget_dir=budget, rules={},
                discovery_fn=Mock(return_value={'status': 'completed', 'urls': ['https://example.com/about']}),
                read_fn=lambda url: {'url': url, 'title': 'About', 'text': 'Headquarters in China'},
                propose_fn=Mock(return_value={'facts': [{'field': 'country', 'value': '中国',
                    'url': 'https://example.com/about', 'title': 'About', 'quote': 'Headquarters in China'}]}))
        self.assertEqual(enriched['knownLinkResearch']['filled'], 1)
        original_journal = (budget / 'ledger.json').read_bytes()
        # The researched overview was never written, and discovery URLs exist
        # only in the private journal when reconstruction starts.
        self.assertEqual(json.loads((w / 'data/company-overview/current.json').read_text())['companies'], [])
        save(self.root / 'work/company-research-budget/lease.json', {'owner': 'live-run:1'})
        with patch.object(candidate, 'validate', return_value={'news': 1}), \
                patch.object(recovery, 'deny_model', side_effect=AssertionError('must not request')) as network:
            report = recovery.rebuild(self.root, source)
        network.assert_not_called()
        self.assertEqual(report['optionalResearch'], 'replayed_cache_only')
        self.assertEqual(report['optionalResearchReplay']['cacheHits'], 1)
        self.assertEqual(report['optionalResearchReplay']['attempted'], 0)
        self.assertEqual(report['optionalResearchReplay']['pagesFetched'], 0)
        result = json.loads((Path(report['reviewDirectory']) / 'workspace/data/company-overview/current.json').read_text(encoding='utf-8'))
        row = result['companies'][0]
        self.assertEqual(row['country'], '中国')
        self.assertEqual(row['profileUpdatedAt'], original_time)
        self.assertEqual(row['fieldSources']['country'][0]['checkedAt'], original_time)
        self.assertEqual((budget / 'ledger.json').read_bytes(), original_journal)
        self.assertEqual(json.loads((self.root / 'work/company-research-budget/lease.json').read_text())['owner'], 'live-run:1')

    def test_missing_cache_blocks_before_build_or_network(self):
        source = self.cached_fixture(cached=False)
        with patch('build_company_overview.build') as build, patch.object(recovery, 'deny_model') as model:
            with self.assertRaisesRegex(ValueError, '未缓存'):
                recovery.rebuild(self.root, source)
        build.assert_not_called(); model.assert_not_called()
        report = json.loads(next((self.root / 'work/recovery-candidates').glob('*/recovery-report.json')).read_text())
        self.assertEqual(report['missing']['overview'], ['article'])
        self.assertFalse(report['published'])

    def test_old_run_without_model_identity_is_not_guessed(self):
        source = self.cached_fixture()
        state = dict(self.state); state.pop('modelContext')
        save(source / 'state.json', state)
        with self.assertRaisesRegex(ValueError, '模型标识'):
            recovery.rebuild(self.root, source)

    def test_formal_updates_after_original_run_are_not_overwritten(self):
        source = self.cached_fixture()
        save(self.root / 'web/public/reviewed-news.json', {'manualUpdate': True})
        with self.assertRaisesRegex(ValueError, '原运行基线'):
            recovery.rebuild(self.root, source)
        self.assertTrue(json.loads((self.root / 'web/public/reviewed-news.json').read_text())['manualUpdate'])

    def test_interruption_preserves_completed_company_cache(self):
        from company_index.extraction import extract_articles
        tx = tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        tx.setdefault('companyOverview', {}).update(concurrency=1, max_new_articles_per_run=2)
        articles = [{'id': str(i), 'title': 'Article', 'sourceName': 'Source', 'category': 'release', 'content_text': 'Enough source evidence'} for i in range(2)]
        calls = []
        def model(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise recovery.NeedsModel('simulated process interruption')
            return '{"companies": []}'
        path = self.root / 'cache.json'
        with patch.dict(os.environ, {'LLM_MODEL': 'test-model'}):
            with self.assertRaises(recovery.NeedsModel):
                extract_articles(tx, articles, path, model)
            cache = json.loads(path.read_text())
            self.assertEqual(cache[cache_key(tx, articles[0])]['status'], 'complete')
            self.assertNotIn(cache_key(tx, articles[1]), cache)
