import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.collection_window import main, scheduled_end
from automation.schedule_audit import timing_report
import run_pipeline


class ScheduledWindowTests(unittest.TestCase):
    def setUp(self):
        self.env = {'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '123',
                    'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_SHA': 'a' * 40}

    def report(self, created='2026-09-24T01:30:00Z', started='2026-09-25T02:00:00Z'):
        return timing_report({'id': 123, 'run_attempt': 2, 'head_sha': 'a' * 40,
                              'event': 'schedule', 'created_at': created, 'run_started_at': started})

    def test_beijing_cutoff_survives_afternoon_trigger_and_next_day_runner_start(self):
        for created in ('2026-09-24T01:30:00Z', '2026-09-24T06:21:49Z'):
            with self.subTest(created=created):
                self.assertEqual(scheduled_end(self.report(created), self.env).isoformat(),
                                 '2026-09-24T09:30:00+08:00')

    def test_creation_before_cutoff_uses_last_elapsed_cutoff_not_future_news(self):
        self.assertEqual(scheduled_end(self.report('2026-09-24T00:00:00Z'), self.env).isoformat(),
                         '2026-09-23T09:30:00+08:00')

    def test_utc_date_is_converted_before_choosing_cutoff(self):
        self.assertEqual(scheduled_end(self.report('2026-09-24T20:00:00Z'), self.env).isoformat(),
                         '2026-09-24T09:30:00+08:00')

    def test_unavailable_stale_or_manual_evidence_cannot_start_scheduled_paid_run(self):
        cases = [{'status': 'unavailable'}, {'event': 'workflow_dispatch'}, {'runId': 999},
                 {'runAttempt': 1}, {'headSha': 'b' * 40}, {'createdAtBeijing': '2026-09-24T09:30:00'}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                scheduled_end({**self.report(), **changes}, self.env)

    def test_manual_run_does_not_read_audit_or_override_rolling_window(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(main(directory, {'GITHUB_EVENT_NAME': 'workflow_dispatch'}), 0)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_missing_audit_stops_before_collection(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(directory, self.env), 1)

    def test_outputs_feed_exact_window_to_offline_production_plan(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            (root / 'work').mkdir()
            (root / 'work/schedule-audit.json').write_text(json.dumps(self.report()), encoding='utf-8')
            env = {**self.env, 'GITHUB_OUTPUT': str(root / 'outputs'),
                   'GITHUB_STEP_SUMMARY': str(root / 'summary')}
            self.assertEqual(main(root, env), 0)
            output = dict(line.split('=', 1) for line in (root / 'outputs').read_text().splitlines())
        with patch.dict('os.environ', {}, clear=True), contextlib.redirect_stdout(io.StringIO()) as capture:
            self.assertEqual(run_pipeline.main(['run', '--stage', 'all', '--source-mode', 'direct-only',
                '--skip-search', '--window-mode', 'ten-am', '--cutoff-time', '09:30',
                '--date', output['date'], '--window-end', output['window_end'], '--dry-run']), 0)
        plan = json.loads(capture.getvalue())
        self.assertEqual(plan['collectionWindow']['start'], '2026-09-23T09:30:00+08:00')
        self.assertEqual(plan['collectionWindow']['end'], '2026-09-24T09:30:00+08:00')
        self.assertEqual(plan['sourceMode'], 'direct-only')
        self.assertTrue(plan['publish'])


if __name__ == '__main__':
    unittest.main()
