import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from company_index.daily_research import enrich
from company_index.research import propose, proposal_key
from company_index.research_budget import ResearchBudget, BudgetUnavailable, atomic_json
from llm_failures import LLMRequestError


TX = {'model': {'model': 'offline-budget-model'}}
NOW = '2026-09-20T12:00:00+08:00'


def company(name='X'):
    return {'id': 'company:' + name, 'company_name': name, 'country': None,
            'business': 'Existing', 'fieldSources': {}, 'lastSeenAt': '2026-09-19',
            'sourceArticles': [{'url': 'https://example.com/' + name}]}


class ResearchBudgetTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.budget = self.root / 'budget'
        for target, value in [('company_index.daily_research.now_bj_iso', NOW),
                              ('company_index.cloud_research_lease.today_bj', '2026-09-20')]:
            p = patch(target, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.dict('os.environ', {'GITHUB_ACTIONS': '', 'COMPANY_RESEARCH_BUDGET_READY': ''})
        p.start(); self.addCleanup(p.stop)
        self.reader = Mock(side_effect=lambda url: {'url': url, 'title': 'About', 'text': 'China'})
        self.model = Mock(return_value={'facts': [{'field': 'country', 'value': '中国',
            'url': 'https://example.com/X', 'title': 'About', 'quote': 'China'}]})

    def run_enrich(self, data=None, run='run1', **kwargs):
        return enrich(data or {'companies': [company()]}, TX, self.root / run,
            rules={}, budget_dir=self.budget, read_fn=kwargs.pop('read_fn', self.reader),
            propose_fn=kwargs.pop('propose_fn', self.model), **kwargs)

    def usage(self):
        return ResearchBudget(self.budget, clock=lambda: NOW).usage()

    def test_unpublished_success_replays_without_pages_slots_or_new_dates(self):
        original = {'companies': [company()]}
        first = self.run_enrich(original)
        usage = self.usage()
        with patch('company_index.daily_research.now_bj_iso', return_value='2026-09-21T12:00:00+08:00'):
            second = self.run_enrich(original, run='new-run')
        self.reader.assert_called_once(); self.model.assert_called_once()
        self.assertEqual(second['companies'], first['companies'])
        self.assertEqual(second['companies'][0]['profileUpdatedAt'], NOW)
        self.assertEqual(second['knownLinkResearch']['attempted'], 0)
        self.assertEqual(second['knownLinkResearch']['cacheHits'], 1)
        self.assertEqual(self.usage(), usage)
        self.assertEqual(second['knownLinkResearch']['dailyUsageAfter'], dict(entities=0, pages=0, requests=0))

    def test_unpublished_five_results_cannot_fund_another_batch(self):
        data = {'companies': [company(str(i)) for i in range(8)]}
        self.model.return_value = {'facts': []}
        first = self.run_enrich(data)
        second = self.run_enrich(data, run='unpublished-rerun')
        self.assertEqual(self.model.call_count, 5)
        self.assertEqual(self.reader.call_count, 5)
        self.assertEqual(second['knownLinkResearch']['cacheHits'], 5)
        self.assertEqual(second['knownLinkResearch']['deferred'], 3)
        self.assertEqual(second['knownLinkResearch']['dailyUsageAfter'], first['knownLinkResearch']['dailyUsageAfter'])

    def test_failures_and_inflight_reservations_survive_new_run_and_date(self):
        self.model.side_effect = TimeoutError('private-error')
        self.run_enrich()
        with patch('company_index.daily_research.now_bj_iso', return_value='2026-09-21T12:00:00+08:00'):
            second = self.run_enrich(run='new-run')
        self.model.assert_called_once(); self.reader.assert_called_once()
        self.assertEqual(second['knownLinkResearch']['skippedUnchanged'], 1)
        self.assertNotIn('private-error', (self.budget / 'ledger.json').read_text())

    def test_reservations_are_durable_before_each_external_call(self):
        def read(url):
            self.assertEqual(self.usage(), dict(entities=1, pages=1, requests=0))
            return {'url': url, 'title': 'About', 'text': 'China'}
        def model(*args, **kwargs):
            self.assertEqual(self.usage(), dict(entities=1, pages=1, requests=1))
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_enrich(read_fn=read, propose_fn=model)
        second = self.run_enrich(run='after-interruption')
        self.reader.assert_not_called(); self.model.assert_not_called()
        self.assertEqual(second['knownLinkResearch']['skippedUnchanged'], 1)
        self.assertEqual(self.usage()['requests'], 1)

    def test_result_written_before_event_finalization_is_recovered(self):
        def model(tx, packet, directory, **kwargs):
            result = propose(tx, packet, directory, llm_fn=Mock(return_value=json.dumps(
                {'entity_type': 'company', 'facts': [{'field': 'country', 'value': '中国',
                 'source_index': 0, 'quote': 'China'}]})), **kwargs)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_enrich(propose_fn=model)
        result = self.run_enrich(run='recover')
        self.assertEqual(result['companies'][0]['country'], '中国')
        self.assertEqual(result['knownLinkResearch']['attempted'], 0)
        self.assertEqual(self.reader.call_count, 1)
        self.model.assert_not_called()

    def test_existing_run_success_cache_avoids_model_slot(self):
        packet = {'record_name': 'X', 'current_record': {f: company().get(f) for f in
            ('founded', 'country', 'team', 'business', 'investors', 'total_funding', 'valuation')},
            'missing_fields': ['founded', 'country', 'team', 'investors', 'total_funding', 'valuation'],
            'sources': [{'url': 'https://example.com/X', 'title': 'About', 'text': 'China'}]}
        atomic_json(self.root / 'run1' / (proposal_key(TX, packet, isolate_invalid=True) + '.json'), self.model.return_value)
        result = self.run_enrich()
        self.model.assert_not_called()
        self.assertEqual(result['knownLinkResearch']['attempted'], 0)
        self.assertEqual(self.usage()['requests'], 0)

    def test_two_local_runs_share_remaining_budget_with_run_limit_one(self):
        def model(tx, packet, directory, **kwargs):
            return propose(tx, packet, directory, llm_fn=Mock(return_value='{"entity_type":"company","facts":[]}'), **kwargs)
        self.run_enrich({'companies': [company('first')]}, propose_fn=model, max_requests=1)
        result = self.run_enrich({'companies': [company('second')]}, run='next', propose_fn=model, max_requests=1)
        self.assertEqual(result['knownLinkResearch']['attempted'], 1)
        self.assertEqual(result['knownLinkResearch']['failed'], 0)
        self.assertEqual(self.usage()['requests'], 2)

    def test_saved_system_failure_stops_new_inputs_without_published_state(self):
        self.model.side_effect = LLMRequestError('authentication', 401)
        self.run_enrich()
        result = self.run_enrich({'companies': [company('other')]}, run='new')
        self.model.assert_called_once(); self.reader.assert_called_once()
        self.assertTrue(result['knownLinkResearch']['circuitOpen'])

    def test_unknown_legacy_is_imported_once_and_remains_conservative(self):
        data = {'companies': [company()], 'knownLinkResearchState': {
            str(i): {'checkedAt': None, 'status': 'completed'} for i in range(5)}}
        self.run_enrich(data)
        self.run_enrich(data, run='new')
        self.reader.assert_not_called(); self.model.assert_not_called()
        self.assertEqual(self.usage(), dict(entities=5, pages=10, requests=5))

    def test_unavailable_and_corrupt_ledgers_fail_closed(self):
        self.budget.mkdir()
        for filename, value in [('ledger.lock', ''), ('ledger.json', 'bad-json')]:
            path = self.budget / filename
            path.write_text(value)
            result = self.run_enrich()
            self.assertIn('budgetUnavailable', result['knownLinkResearch'])
            self.reader.assert_not_called(); self.model.assert_not_called()
            path.unlink()

    def test_cloud_requires_ready_same_owner_same_day_but_allows_replay(self):
        first = self.run_enrich()
        lease = dict(schemaVersion=1, day='2026-09-20', owner='123:1',
                     limits=dict(entities=5, pages=10, requests=5), status='reserved')
        atomic_json(self.budget / 'lease.json', lease)
        with patch.dict('os.environ', {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '999',
                'GITHUB_RUN_ATTEMPT': '1', 'COMPANY_RESEARCH_BUDGET_READY': '1'}):
            replay = self.run_enrich(run='other-owner')
            denied = self.run_enrich({'companies': [company('new')]})
        self.assertEqual(replay['companies'], first['companies'])
        self.assertEqual(denied['knownLinkResearch']['notAttempted'][0]['reason'], 'cloud_lease_unavailable')
        with patch.dict('os.environ', {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123',
                'GITHUB_RUN_ATTEMPT': '1', 'COMPANY_RESEARCH_BUDGET_READY': ''}):
            denied = self.run_enrich({'companies': [company('new')]})
        self.assertEqual(denied['knownLinkResearch']['notAttempted'][0]['reason'], 'cloud_budget_not_ready')
        self.model.assert_called_once(); self.reader.assert_called_once()

    def test_cloud_valid_lease_consumes_and_midflight_day_change_blocks_model(self):
        atomic_json(self.budget / 'lease.json', dict(schemaVersion=1, day='2026-09-20', owner='123:1',
                    limits=dict(entities=5, pages=10, requests=5), status='reserved'))
        with patch.dict('os.environ', {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123',
                'GITHUB_RUN_ATTEMPT': '1', 'COMPANY_RESEARCH_BUDGET_READY': '1'}):
            self.run_enrich()
        self.assertEqual(self.model.call_count, 1)
        clock = Mock(return_value=NOW)
        def reader(url):
            clock.return_value = '2026-09-21T00:00:00+08:00'
            return self.reader(url)
        with patch('company_index.daily_research.now_bj_iso', clock):
            result = self.run_enrich({'companies': [company('cross-day')]}, read_fn=reader)
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(result['knownLinkResearch']['budgetUnavailable'], 'day_changed')
        self.assertEqual(self.usage()['requests'], 1)

    def test_replay_only_recovers_unpublished_discovery_urls_and_never_calls_services(self):
        discovery = Mock(return_value={'status': 'completed', 'urls': ['https://official.example/about']})
        first = self.run_enrich(discovery_fn=discovery)
        forbidden = Mock(side_effect=AssertionError('external call during replay'))
        original_ledger = (self.budget / 'ledger.json').read_bytes()
        with patch('company_index.daily_research.now_bj_iso', return_value='2026-09-21T12:00:00+08:00'):
            replay = self.run_enrich({'companies': [company(), company('unknown')]}, replay_only=True,
                run='recovery', discovery_fn=forbidden, read_fn=forbidden, propose_fn=forbidden)
        forbidden.assert_not_called()
        self.assertEqual(replay['companies'][0], first['companies'][0])
        self.assertEqual(replay['knownLinkResearch']['cacheHits'], 1)
        self.assertEqual(replay['knownLinkResearch']['notAttempted'][0]['reason'], 'cache_missing')
        self.assertEqual((self.budget / 'ledger.json').read_bytes(), original_ledger)

    def test_normal_run_recovers_lost_discovery_success_without_reserving_again(self):
        current = company()
        current['sourceArticles'].append({'url': 'https://example.com/second-news'})
        first = self.run_enrich({'companies': [current]}, discovery_fn=Mock(return_value={
            'status': 'completed', 'urls': ['https://official.example/about']}))
        usage = self.usage()
        calls = self.reader.call_count
        result = self.run_enrich({'companies': [current]}, run='unpublished-new-run')
        self.assertEqual(result['companies'], first['companies'])
        self.assertEqual(result['knownLinkResearch']['cacheHits'], 1)
        self.assertEqual(result['knownLinkResearch']['attempted'], 0)
        self.assertEqual(self.reader.call_count, calls)
        self.model.assert_called_once()
        self.assertEqual(self.usage(), usage)

    def test_normal_run_does_not_hide_a_new_official_url_behind_older_success(self):
        self.run_enrich(discovery_fn=Mock(return_value={'status': 'completed',
            'urls': ['https://official.example/about']}))
        data = {'companies': [company()], 'companyDiscovery': {'history': {
            'company:X': {'urls': ['https://new-official.example/legal']}}}}
        result = self.run_enrich(data, run='new-official-input')
        self.assertEqual(result['knownLinkResearch']['cacheHits'], 0)
        self.assertEqual(result['knownLinkResearch']['attempted'], 1)
        self.assertEqual(self.model.call_count, 2)
        self.assertEqual(self.usage()['requests'], 2)

    def test_replay_never_overwrites_newer_facts_or_profile_time(self):
        self.run_enrich()
        current = company()
        current.update(country='美国', profileUpdatedAt='2026-09-21T12:00:00+08:00')
        result = self.run_enrich({'companies': [current]}, replay_only=True)
        self.assertEqual(result['companies'][0], current)
        self.assertEqual(result['knownLinkResearch']['filled'], 0)
        self.model.assert_called_once()
        current['country'] = None
        result = self.run_enrich({'companies': [current]}, replay_only=True)
        self.assertEqual(result['companies'][0]['country'], '中国')
        self.assertEqual(result['companies'][0]['profileUpdatedAt'], current['profileUpdatedAt'])
        self.assertEqual(result['companies'][0]['fieldSources']['country'][0]['checkedAt'], NOW)

    def test_replay_discovery_fallback_is_bound_to_original_entity_and_news_input(self):
        self.run_enrich(discovery_fn=Mock(return_value={'status': 'completed', 'urls': ['https://official.example/about']}))
        current = company()
        current['lastSeenAt'] = '2026-09-20'
        result = self.run_enrich({'companies': [current]}, replay_only=True)
        self.assertIsNone(result['companies'][0]['country'])
        self.assertEqual(result['knownLinkResearch']['cacheHits'], 0)
        self.model.assert_called_once()

    def test_day_change_between_pages_stops_second_page_and_model(self):
        current = company()
        current['sourceArticles'].append({'url': 'https://example.com/about'})
        clock = Mock(return_value=NOW)
        def reader(url):
            clock.return_value = '2026-09-21T00:00:00+08:00'
            return self.reader(url)
        with patch('company_index.daily_research.now_bj_iso', clock):
            result = self.run_enrich({'companies': [current]}, read_fn=reader)
        self.reader.assert_called_once(); self.model.assert_not_called()
        self.assertEqual(result['knownLinkResearch']['budgetUnavailable'], 'day_changed')
        self.assertEqual(self.usage(), dict(entities=1, pages=2, requests=0))
