import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from automation.diagnostic_summary import summarize


class SummaryTests(unittest.TestCase):
    def test_accepted_stop_is_not_reported_as_confirmed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'diagnostics').mkdir()
            (root / 'diagnostics/x.json').write_text(json.dumps({
                'taskId': 'task-2', 'stopAccepted': True, 'stopSucceeded': False,
                'remoteStatus': 'private response', 'stopError': 'private error'}))
            value = summarize(root)
            self.assertEqual(value['taskStops'], [{'taskId': 'task-2', 'stopAccepted': True,
                'stopSucceeded': False, 'remoteStatus': 'unknown'}])
            self.assertNotIn('private', json.dumps(value))

    def test_only_cost_numbers_and_stop_status_are_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'cost-report.json').write_text(json.dumps({
                'creditsUsed': 421, 'error': 'private', 'sourceFailures': ['private']}))
            (root / 'diagnostics').mkdir()
            (root / 'diagnostics/x.json').write_text(json.dumps({
                'taskId': 'task-1', 'stopSucceeded': True, 'reason': 'private'}))
            value = summarize(root)
            self.assertEqual(value['costReports'], [{'creditsUsed': 421}])
            self.assertEqual(value['taskStops'], [{'taskId': 'task-1', 'stopSucceeded': True}])
            self.assertNotIn('private', json.dumps(value))
