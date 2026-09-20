import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from automation import schedule_audit
from automation.schedule_audit import timing_report


class ScheduleAuditTest(unittest.TestCase):
    def test_scheduled_run_uses_beijing_calendar_and_creation_time(self):
        report = timing_report({'event':'schedule','created_at':'2026-09-16T06:21:49Z'})
        self.assertEqual(report['expectedSameDayBeijing'], '2026-09-16T09:30:00+08:00')
        self.assertEqual(report['delaySeconds'], 17509)

    def test_manual_afternoon_run_is_not_mislabeled_as_scheduler_delay(self):
        report = timing_report({'event':'workflow_dispatch','created_at':'2026-09-16T06:33:01Z'})
        self.assertNotIn('delaySeconds', report)

    def test_actual_run_start_is_separate_from_diagnostic_and_unknown_job_start(self):
        report = timing_report({'id': 100, 'run_attempt': 2, 'head_sha': 'a' * 40,
            'event': 'schedule', 'created_at': '2026-09-16T01:30:00Z',
            'run_started_at': '2026-09-16T01:34:00Z'})
        self.assertEqual(report['runStartedAtBeijing'], '2026-09-16T09:34:00+08:00')
        self.assertEqual(report['createdToRunStartSeconds'], 240)
        self.assertEqual(report['delaySeconds'], 0)
        self.assertIsNone(report['jobStartedAtBeijing'])
        self.assertEqual(report['runAttempt'], 2)
        self.assertNotEqual(report['runStartedAtBeijing'], report['checkedAtBeijing'])

    def test_missing_start_time_is_unknown_not_diagnostic_time(self):
        report = timing_report({'event': 'schedule', 'created_at': '2026-09-16T01:30:00Z'})
        self.assertIsNone(report['runStartedAtBeijing'])
        self.assertIsNone(report['createdToRunStartSeconds'])
        self.assertIsNone(report['runStartToDiagnosticSeconds'])

    def test_main_persists_safe_json_for_encrypted_and_status_artifacts(self):
        response = {'id': 100, 'run_attempt': 1, 'head_sha': 'a' * 40, 'event': 'schedule',
            'created_at': '2026-09-16T01:30:00Z', 'run_started_at': '2026-09-16T01:30:05Z',
            'extra': 'PRIVATE-API-BODY'}
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'GITHUB_REPOSITORY': 'example/repo', 'GITHUB_RUN_ID': '100',
                    'GITHUB_TOKEN': 'PRIVATE-TOKEN', 'GITHUB_STEP_SUMMARY': ''}), \
                patch.object(schedule_audit, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())), \
                patch('sys.stdout', new_callable=io.StringIO):
            schedule_audit.main(directory)
            saved = Path(directory, 'work/schedule-audit.json').read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE', saved)
        self.assertEqual(json.loads(saved)['createdToRunStartSeconds'], 5)

    def test_api_failure_persists_unavailable_without_raw_error_and_never_blocks(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'GITHUB_REPOSITORY': 'example/repo', 'GITHUB_RUN_ID': '100',
                    'GITHUB_TOKEN': 'PRIVATE-TOKEN', 'GITHUB_STEP_SUMMARY': ''}), \
                patch.object(schedule_audit, 'urlopen', side_effect=HTTPError('PRIVATE-URL', 403, 'PRIVATE-BODY', {}, None)), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            schedule_audit.main(directory)
            saved = Path(directory, 'work/schedule-audit.json').read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE', saved + output.getvalue())
        self.assertEqual(json.loads(saved)['status'], 'unavailable')

    def test_output_failure_does_not_block_pipeline(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            Path(directory, 'work').write_text('not a directory')
            schedule_audit.main(directory)
        self.assertIn('文件无法保存', output.getvalue())
