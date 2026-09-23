"""Explicit full known-link review keeps evidence and durable safety guards."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import build_company_overview
from company_index.daily_research import enrich
from company_index.research import propose
from company_index.research_budget import ResearchBudget
from llm_failures import LLMRequestError


TX = {'model': {'model': 'offline-full-research'}}
NOW = '2026-09-23T12:00:00+08:00'
CLOUD = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
         'COMPANY_RESEARCH_BUDGET_READY': '1'}


def company(n):
    return {'id': f'company:{n}', 'company_name': str(n), 'fieldSources': {},
            'lastSeenAt': '2026-09-22', 'sourceArticles': [
                {'url': f'https://example.com/{n}/{page}'} for page in range(3)]}


class FullKnownLinkResearchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.budget = self.root / 'budget'
        self.reader = Mock(side_effect=lambda url: {'url': url, 'title': 'Known page', 'text': 'Evidence'})
        self.model = Mock(return_value={'facts': []})
        for p in (patch('company_index.daily_research.now_bj_iso', return_value=NOW),
                  patch.dict('os.environ', {'GITHUB_ACTIONS': '', 'LLM_MODEL': '',
                                           'COMPANY_RESEARCH_BUDGET_READY': ''})):
            p.start()
            self.addCleanup(p.stop)

    def run_enrich(self, data, **kwargs):
        return enrich(data, TX, self.root / 'run', rules={}, budget_dir=self.budget,
                      read_fn=kwargs.pop('read_fn', self.reader),
                      propose_fn=kwargs.pop('propose_fn', self.model), **kwargs)

    def write_lease(self, owner='123:1'):
        self.budget.mkdir(parents=True, exist_ok=True)
        (self.budget / 'lease.json').write_text(json.dumps({
            'schemaVersion': 1, 'day': NOW[:10], 'owner': owner,
            'limits': {'entities': 5, 'pages': 10, 'requests': 5}, 'status': 'reserved'}), 'utf-8')

    def test_full_pool_exceeds_old_quota_without_rewriting_old_reservations(self):
        data = {'companies': [company(n) for n in range(12)]}
        limited = self.run_enrich(data)
        self.assertEqual(limited['knownLinkResearch']['attempted'], 5)
        old = json.loads((self.budget / 'ledger.json').read_text('utf-8'))
        discovery = Mock(side_effect=AssertionError('Manus must stay disabled'))
        self.write_lease()
        lease = (self.budget / 'lease.json').read_bytes()
        with patch.dict('os.environ', CLOUD), patch(
                'company_index.cloud_research_lease.today_bj', return_value=NOW[:10]):
            full = self.run_enrich(data, full_review=True, discovery_fn=discovery)
        discovery.assert_not_called()
        report = full['knownLinkResearch']
        self.assertEqual((self.reader.call_count, self.model.call_count), (24, 12))
        self.assertEqual((report['cacheHits'], report['attempted'], report['deferred']), (5, 7, 0))
        self.assertIsNone(report['dailyLimits'])
        self.assertEqual(report['cloudGuard'], 'same_day_owner_lease')
        self.assertEqual(report['batchLimits'], {'entities': 12, 'pages': 24, 'requests': 12})
        self.assertEqual(report['dailyUsageAfter'], {'entities': 12, 'pages': 24, 'requests': 12})
        self.assertEqual((self.budget / 'lease.json').read_bytes(), lease)
        self.assertFalse(report['dailyLimitReached'])
        self.assertTrue(report['discoveryDisabled'])
        updated = json.loads((self.budget / 'ledger.json').read_text('utf-8'))
        for key, value in old['inputs'].items():
            self.assertEqual(updated['inputs'][key], value)
        for key, value in old['requests'].items():
            self.assertEqual(updated['requests'][key], value)
        # The old default quota remains exhausted; full review did not reset it.
        denied = self.run_enrich({'companies': [company('new')]})
        self.assertEqual(denied['knownLinkResearch']['notAttempted'][0]['reason'], 'daily_limit')
        self.assertEqual(self.model.call_count, 12)

    def test_full_cloud_missing_or_foreign_lease_blocks_new_work_but_replays_success(self):
        self.run_enrich({'companies': [company(0)]}, full_review=True)
        ledger = (self.budget / 'ledger.json').read_bytes()
        cached = {str(p.relative_to(self.budget)): p.read_bytes()
                  for p in (self.budget / 'results').glob('*.json')}
        self.reader.reset_mock()
        self.model.reset_mock()
        data = {'companies': [company(0), company(1)]}
        for ready, owner, reason in (
                ('', None, 'cloud_budget_not_ready'),
                ('1', None, 'cloud_lease_unavailable'),
                ('1', '456:1', 'cloud_lease_unavailable')):
            with self.subTest(ready=ready, owner=owner):
                if owner:
                    self.write_lease(owner)
                with patch.dict('os.environ', {**CLOUD, 'COMPANY_RESEARCH_BUDGET_READY': ready}), patch(
                        'company_index.cloud_research_lease.today_bj', return_value=NOW[:10]):
                    result = self.run_enrich(data, full_review=True)
                report = result['knownLinkResearch']
                self.assertEqual((report['attempted'], report['cacheHits'], report['deferred']), (0, 1, 1))
                self.assertEqual(report['notAttempted'][0]['reason'], reason)
                self.assertEqual((self.budget / 'ledger.json').read_bytes(), ledger)
                self.assertEqual({str(p.relative_to(self.budget)): p.read_bytes()
                                  for p in (self.budget / 'results').glob('*.json')}, cached)
        self.reader.assert_not_called()
        self.model.assert_not_called()

    def test_full_review_passes_eighty_real_proposal_limit_without_a_retry(self):
        destination = self.budget / 'model-cache' / NOW[:10]
        destination.mkdir(parents=True)
        (destination / 'requests.json').write_text(json.dumps({'attempts': 80, 'limit': 80}), 'utf-8')
        llm = Mock(return_value='{"entity_type":"company","facts":[]}')
        def proposer(*args, **kwargs):
            self.assertTrue(kwargs['full_review'])
            self.assertIsNone(kwargs['max_requests'])
            # The durable request slot must exist before arbitrary model code.
            usage = ResearchBudget(self.budget, clock=lambda: NOW).usage()
            self.assertEqual(usage['requests'], llm.call_count + 1)
            return propose(*args, **kwargs, llm_fn=llm)
        data = {'companies': [company(n) for n in range(6)]}
        result = self.run_enrich(data, full_review=True, propose_fn=proposer)
        self.assertEqual(result['knownLinkResearch']['attempted'], 6)
        self.assertEqual(llm.call_count, 6)
        self.assertEqual(json.loads((destination / 'requests.json').read_text())['attempts'], 86)
        self.assertIsNone(json.loads((destination / 'requests.json').read_text())['limit'])
        forbidden = Mock(side_effect=AssertionError('replay must not call services'))
        ledger = (self.budget / 'ledger.json').read_bytes()
        replay = self.run_enrich(data, full_review=True, replay_only=True,
                                read_fn=forbidden, propose_fn=forbidden, discovery_fn=forbidden)
        forbidden.assert_not_called()
        self.assertEqual(replay['knownLinkResearch']['cacheHits'], 6)
        self.assertEqual((self.budget / 'ledger.json').read_bytes(), ledger)

    def test_full_mode_authentication_stops_new_inputs_and_persists_failure(self):
        self.model.side_effect = LLMRequestError('authentication', 401)
        result = self.run_enrich({'companies': [company(n) for n in range(8)]}, full_review=True)
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.reader.call_count, 2)
        self.assertTrue(result['knownLinkResearch']['circuitOpen'])
        self.assertEqual(result['knownLinkResearch']['deferred'], 7)
        repeat = self.run_enrich({'companies': [company('new')]}, full_review=True)
        self.assertTrue(repeat['knownLinkResearch']['circuitOpen'])
        self.assertEqual(self.model.call_count, 1)

    def test_full_mode_content_failures_are_isolated_and_never_retried(self):
        self.model.side_effect = ValueError('字段缺少逐字来源证据，拒绝写入')
        data = {'companies': [company(n) for n in range(7)]}
        result = self.run_enrich(data, full_review=True)
        self.assertEqual(self.model.call_count, 7)
        self.assertEqual(result['knownLinkResearch']['failed'], 7)
        self.assertFalse(result['knownLinkResearch']['circuitOpen'])
        repeat = self.run_enrich(data, full_review=True)
        self.assertEqual(repeat['knownLinkResearch']['skippedUnchanged'], 7)
        self.assertEqual(self.model.call_count, 7)

    def test_proposal_unbounded_mode_requires_both_explicit_flags(self):
        packet = {'record_name': 'X', 'sources': [{'url': 'https://example.com', 'title': 'Known', 'text': 'Evidence'}]}
        llm = Mock()
        with self.assertRaises(ValueError):
            propose(TX, packet, self.root / 'propose', allow_paid=True, max_requests=None, llm_fn=llm)
        with self.assertRaises(ValueError):
            propose(TX, packet, self.root / 'propose', full_review=True, max_requests=None, llm_fn=llm)
        llm.assert_not_called()

    def test_full_review_cli_implies_known_pages_and_rejects_manus_discovery(self):
        data = {'companies': [], 'stats': {}}
        with patch.object(build_company_overview, 'build', return_value=data), \
             patch.object(build_company_overview.tag_news, 'load_taxonomy', return_value=TX), \
             patch.object(build_company_overview, 'validate'), \
             patch('company_index.daily_research.enrich', return_value=data) as review:
            self.assertEqual(build_company_overview.main(['--research-full-review', '--no-promote']), 0)
        self.assertTrue(review.call_args.kwargs['full_review'])
        self.assertIsNone(review.call_args.kwargs['discovery_fn'])
        with patch.object(build_company_overview, 'build') as build, self.assertRaises(SystemExit):
            build_company_overview.main(['--research-full-review', '--discover-company'])
        build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
