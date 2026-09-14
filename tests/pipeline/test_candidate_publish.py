import sys
import os
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from automation import candidate
from automation.publish import ALLOWED
from automation.publish import save
from source_status import reason_code


class CandidatePublish(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'work/example/workspace'
        for rel in (*ALLOWED, 'inputs'):
            (self.workspace / rel).mkdir(parents=True)
            (self.workspace / rel / 'example.json').write_text('{}')
        self.mock = patch.object(candidate, 'validate', return_value={'news': 1})
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_publish_keeps_source_and_is_idempotent(self):
        run, _ = candidate.prepare(self.root, self.workspace)
        candidate.promote(self.root, run)
        self.assertTrue((self.workspace / 'inputs/example.json').exists())
        self.assertTrue((self.root / 'web/public/example.json').exists())
        self.assertFalse((self.root / 'inputs').exists())
        self.assertEqual(candidate.promote(self.root, run), {'news': 1})

    def test_changed_candidate_is_rejected(self):
        run, _ = candidate.prepare(self.root, self.workspace)
        (run / 'workspace/web/public/example.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, '候选文件已变化'):
            candidate.promote(self.root, run)

    def test_new_formal_data_is_not_overwritten(self):
        run, _ = candidate.prepare(self.root, self.workspace)
        path = self.root / 'web/public'
        path.mkdir(parents=True)
        (path / 'new.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, '正式数据已变化'):
            candidate.promote(self.root, run)
        self.assertTrue((path / 'new.json').exists())

    def test_code_change_requires_review(self):
        run, _ = candidate.prepare(self.root, self.workspace)
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/new.py').write_text('pass')
        with self.assertRaisesRegex(ValueError, '代码或配置已变化'):
            candidate.promote(self.root, run)

    def test_lock_and_external_path_are_rejected(self):
        with self.assertRaises(ValueError):
            candidate.prepare(self.root, self.root)
        run, _ = candidate.prepare(self.root, self.workspace)
        (self.root / 'work/pipeline.lock').touch()
        with self.assertRaises(FileExistsError):
            candidate.promote(self.root, run)


class SourceReasons(unittest.TestCase):
    def test_unstarted_and_stopped_are_distinct(self):
        self.assertEqual(reason_code('failed','cost_circuit_open: repeated credit stops; task not created'), 'not_started_budget')
        self.assertEqual(reason_code('failed','Observed credit threshold reached: 21 >= 20'), 'budget_stopped')
        self.assertEqual(reason_code('partial','boundary_unverified'), 'boundary_unverified')
        self.assertEqual(reason_code('failed',None), 'unavailable')

    def test_review_cli_sets_beijing_cutoff(self):
        import run_pipeline
        def reviewed(root, workspace):
            self.assertEqual(os.environ['AIHOT_CUTOFF_TIME'], '09:30')
            return Path('review'), {'news': 1}
        with patch.object(candidate, 'prepare', side_effect=reviewed), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_pipeline.main(['review-candidate', '--candidate', 'work/example']), 0)


class CandidateConsistency(unittest.TestCase):
    def test_web_news_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(candidate, 'validate_candidates'):
            root = Path(temp)
            w = root / 'work/w'
            window = {'start':'2026-09-13T09:30:00+08:00','end':'2026-09-14T09:30:00+08:00'}
            status = {'collectionWindow':window}
            save(w / 'inputs/processed.json', {'collectionWindow':window,'collectionStatus':status,
                'items':[{'id':'a','title':'original'}]})
            save(w / 'web/public/snapshot.json', {'collectionWindow':window,'collectionStatus':status,
                'all':{'items':[{'id':'a','title':'changed'}]}})
            save(w / 'data/manus/current.json', {'collectionStatus':status})
            with self.assertRaisesRegex(ValueError, '网页内容不一致'):
                candidate.validate(w, root)
