"""Cloud lease tests are entirely offline, including GitHub history responses."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from company_index import cloud_research_lease as lease


DAY = '2026-09-20'
OWNER = '100:1'
ENDPOINT = 'https://api.github.com/repos/example/repo/actions/workflows/fetch-manus.yml/runs'
ENV = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '100', 'GITHUB_RUN_ATTEMPT': '1',
       'GITHUB_REPOSITORY': 'example/repo', 'GITHUB_TOKEN': 'test-only-token'}


def run(run_id=100, created='2026-09-20T02:00:00Z', updated='2026-09-20T03:00:00Z', **extra):
    return {'id': run_id, 'created_at': created, 'updated_at': updated,
            'run_started_at': created, 'run_attempt': 1, 'status': 'completed', **extra}


def page(runs, count=None, link=''):
    return {'total_count': len(runs) if count is None else count, 'workflow_runs': runs}, link


class CloudResearchLeaseTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, ENV, clear=True).start()
        patch.object(lease, 'today_bj', return_value=DAY).start()
        self.api = patch.object(lease, '_get_page', return_value=page([run()])).start()

    def reserve(self):
        return lease.reserve(self.directory, DAY, OWNER)

    def test_first_run_reserves_once_and_existing_lease_needs_no_history(self):
        value = self.reserve()
        self.assertEqual(value['limits'], {'entities': 5, 'pages': 10, 'requests': 5})
        self.assertTrue(lease.check(self.directory, DAY, OWNER))
        self.assertEqual(self.reserve(), value)
        self.api.assert_called_once_with(ENDPOINT + '?per_page=100&page=1', 'test-only-token')

    def test_cache_eviction_does_not_reopen_used_day(self):
        self.api.return_value = page([run(), run(99, conclusion='failure')])
        with self.assertRaisesRegex(ValueError, 'day_already_used'):
            self.reserve()
        self.assertFalse((self.directory / 'lease.json').exists())

    def test_beijing_boundary_and_created_yesterday_started_today_are_occupied(self):
        old = '2026-09-19T14:00:00Z'
        for prior in [run(99, old, '2026-09-19T16:00:00Z'),
                      run(99, old, '2026-09-20T01:00:00Z', run_started_at='2026-09-20T00:00:00Z'),
                      run(99, old, old, status='queued'),
                      run(99, old, '2026-09-20T01:00:00Z', run_attempt=2)]:
            with self.subTest(prior=prior):
                self.api.return_value = page([run(), prior])
                with self.assertRaisesRegex(ValueError, 'day_already_used'):
                    self.reserve()

    def test_runs_completed_before_beijing_day_do_not_block(self):
        self.api.return_value = page([run(), run(99, '2026-09-19T14:00:00Z', '2026-09-19T15:59:59Z')])
        self.reserve()
        self.assertTrue(lease.check(self.directory, DAY, OWNER))

    def test_rerun_cannot_reserve_after_cache_loss(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '2'}):
            with self.assertRaisesRegex(ValueError, 'rerun_without_cache'):
                lease.reserve(self.directory, DAY, '100:2')
        self.api.assert_not_called()

    def test_other_owner_or_corrupt_lease_never_overwritten(self):
        original = self.reserve()
        path = self.directory / 'lease.json'
        for value in [{**original, 'owner': '99:1'}, {**original, 'limits': {'entities': 50}},
                      {**original, 'schemaVersion': True}, {**original, 'private': 'forbidden'}]:
            with self.subTest(value=value):
                path.write_text(json.dumps(value), encoding='utf-8')
                before = path.read_bytes()
                self.assertFalse(lease.check(self.directory, DAY, OWNER))
                with self.assertRaisesRegex(ValueError, 'existing_invalid_or_other_owner'):
                    self.reserve()
                self.assertEqual(before, path.read_bytes())
        self.assertEqual(self.api.call_count, 1)

    def test_day_rollover_and_forged_owner_close_existing_lease(self):
        self.reserve()
        with patch.object(lease, 'today_bj', return_value='2026-09-21'):
            self.assertFalse(lease.check(self.directory, DAY, OWNER))
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '101'}):
            self.assertFalse(lease.check(self.directory, DAY, OWNER))

    def test_full_pagination_checks_other_run_not_on_first_page(self):
        link = '<' + ENDPOINT + '?per_page=100&page=2>; rel="next"'
        self.api.side_effect = [page([run()], 2, link), page([run(99)], 2)]
        with self.assertRaisesRegex(ValueError, 'day_already_used'):
            self.reserve()
        self.assertEqual(self.api.call_count, 2)

    def test_complete_pagination_can_prove_first_run(self):
        link = '<' + ENDPOINT + '?page=2&per_page=100>; rel="next"'
        self.api.side_effect = [page([run()], 2, link),
            page([run(99, '2026-09-18T00:00:00Z', '2026-09-18T01:00:00Z')], 2)]
        self.reserve()
        self.assertEqual(self.api.call_count, 2)

    def test_incomplete_malformed_or_missing_current_history_closes(self):
        for response in [page([run()], 2), page([], 0), page([run(99)], 1),
                         page([run()], 1, '<https://evil.invalid/page>; rel="next"'),
                         page([run(updated=None)]), page([run(), run()]),
                         ({'total_count': 1, 'workflow_runs': {}}, '')]:
            with self.subTest(response=response):
                self.api.return_value = response
                with self.assertRaises(ValueError):
                    self.reserve()
                self.assertFalse((self.directory / 'lease.json').exists())

    def test_pagination_budget_exhausted_closes(self):
        with patch.object(lease, 'MAX_PAGES', 1):
            self.api.return_value = page([run()], 2, '<' + ENDPOINT + '?per_page=100&page=2>; rel="next"')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                self.reserve()

    def test_missing_token_fails_without_request(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': ''}):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                self.reserve()
        self.api.assert_not_called()

    def test_local_reservation_uses_same_schema_without_github(self):
        with patch.dict(os.environ, {}, clear=True):
            lease.reserve(self.directory, DAY, 'local:1')
            self.assertTrue(lease.check(self.directory, DAY, 'local:1'))
        self.api.assert_not_called()


class LeaseTransportAndWorkflowTest(unittest.TestCase):
    def test_api_error_does_not_expose_url_token_or_response(self):
        with patch.object(lease, 'build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError('PRIVATE-URL', 403, 'PRIVATE-BODY', {}, None)
            with self.assertRaisesRegex(ValueError, '^research_lease_history_unavailable$'):
                lease._get_page(ENDPOINT, 'PRIVATE-TOKEN')
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_workflow_requires_persisted_exact_lease_and_checks_owner_before_ready(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/fetch-manus.yml').read_text(encoding='utf-8')
        blocks = re.split(r'\n      - ', workflow)
        steps = {re.search(r'\n        id: ([\w-]+)', b).group(1): b for b in blocks
                 if re.search(r'\n        id: ([\w-]+)', b)}
        restore = steps['company-research-restore']
        self.assertIn("!inputs.dry_run", restore)
        self.assertIn("inputs.stage == 'all' || inputs.stage == 'overview'", restore)
        self.assertNotIn('inputs.source_mode', restore)
        self.assertIn("github.event_name == 'schedule'", restore)
        for suffix, previous in [('reserve', 'restore'), ('save', 'reserve'),
                                 ('confirm', 'save'), ('ready', 'confirm')]:
            block = steps['company-research-' + suffix]
            self.assertIn("steps.company-research-" + previous + ".outcome == 'success'", block)
            self.assertIn('continue-on-error: true', block)
        self.assertIn("outputs.cache-hit == 'true'", steps['company-research-ready'])
        self.assertIn('--check --day', steps['company-research-ready'])
        self.assertIn('fail-on-cache-miss: true', steps['company-research-confirm'])
        self.assertIn("COMPANY_RESEARCH_BUDGET_READY: ${{ steps.company-research-ready.outcome == 'success'", workflow)
        # Private ledger and successful proposals never enter an Actions cache.
        for suffix in ('restore', 'save', 'confirm'):
            self.assertIn('path: work/company-research-budget/lease.json\n', steps['company-research-' + suffix])
            self.assertNotIn('restore-keys:', steps['company-research-' + suffix])


if __name__ == '__main__':
    unittest.main()
