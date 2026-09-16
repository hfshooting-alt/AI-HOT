import unittest
from automation.schedule_audit import timing_report


class ScheduleAuditTest(unittest.TestCase):
    def test_scheduled_run_uses_beijing_calendar_and_creation_time(self):
        report = timing_report({'event':'schedule','created_at':'2026-09-16T06:21:49Z'})
        self.assertEqual(report['expectedSameDayBeijing'], '2026-09-16T09:30:00+08:00')
        self.assertEqual(report['delaySeconds'], 17509)

    def test_manual_afternoon_run_is_not_mislabeled_as_scheduler_delay(self):
        report = timing_report({'event':'workflow_dispatch','created_at':'2026-09-16T06:33:01Z'})
        self.assertNotIn('delaySeconds', report)
