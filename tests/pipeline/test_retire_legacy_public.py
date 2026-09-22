"""Candidate-only retirement never edits required data or production paths."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import retire_legacy_public as retirement


class RetireLegacyPublicTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'work').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='retirement-test-', dir=ROOT / 'work')
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / 'data').mkdir()
        self.public = self.workspace / 'web/public'
        self.public.mkdir(parents=True)
        for name in retirement.REQUIRED | retirement.OPTIONAL:
            (self.public / name).write_text('{}' if name.endswith('.json') else '<svg/>', encoding='utf-8')
        for name in ['history/2026-09-22.html', 'weekly/2026-09-14.json', 'reviewed-news.json',
                     'company-research-review.html', 'company-profile-review.json', 'file.svg']:
            path = self.public / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('old evidence', encoding='utf-8')

    def test_plan_is_read_only_for_public_and_apply_keeps_required_bytes(self):
        before = {p.relative_to(self.public): p.read_bytes() for p in self.public.rglob('*') if p.is_file()}
        plan = retirement.retire(self.workspace)
        self.assertEqual(len(plan['retire']), 6)
        self.assertEqual(before, {p.relative_to(self.public): p.read_bytes() for p in self.public.rglob('*') if p.is_file()})
        report = retirement.retire(self.workspace, apply=True)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(set(p.name for p in self.public.iterdir()), retirement.REQUIRED | retirement.OPTIONAL)
        for name in retirement.REQUIRED | retirement.OPTIONAL:
            self.assertEqual((self.public / name).read_bytes(), before[Path(name)])
        self.assertEqual(retirement.retire(self.workspace, apply=True)['deleted'], [])

    def test_production_root_and_work_root_are_rejected(self):
        for path in [ROOT, ROOT / 'web', ROOT / 'web/public', ROOT / 'work']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                retirement.retire(path, apply=True)

    def test_unknown_json_requires_explicit_keep_and_cannot_escape(self):
        (self.public / 'source-status.json').write_text('{"sources":[]}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            retirement.retire(self.workspace, apply=True)
        self.assertTrue((self.public / 'reviewed-news.json').exists())
        for name in ['../secret.json', '/secret.json', 'history/old.json', 'reviewed-news.json', 'nested\\file.json']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                retirement.retire(self.workspace, keep=[name])
        report = retirement.retire(self.workspace, apply=True, keep=['source-status.json'])
        self.assertEqual(report['explicitKeeps'], ['source-status.json'])
        self.assertTrue((self.public / 'source-status.json').exists())

    def test_reparse_point_is_rejected_before_any_deletion(self):
        actual = retirement._is_link
        with patch.object(retirement, '_is_link', side_effect=lambda p: p.name == 'history' or actual(p)):
            with self.assertRaisesRegex(ValueError, 'links/junctions'):
                retirement.retire(self.workspace, apply=True)
        self.assertTrue((self.public / 'reviewed-news.json').exists())

    def test_partial_filesystem_failure_has_private_incomplete_audit(self):
        unlink = Path.unlink
        def fail(path, *args, **kwargs):
            if path.name == 'reviewed-news.json':
                raise OSError('disk failure')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail), self.assertRaises(OSError):
            retirement.retire(self.workspace, apply=True)
        audit = json.loads((self.workspace / retirement.AUDIT_NAME).read_text(encoding='utf-8'))
        self.assertEqual(audit['status'], 'incomplete')
        self.assertEqual(audit['errorType'], 'OSError')
        self.assertFalse(audit['published'])
        for name in retirement.REQUIRED:
            self.assertTrue((self.public / name).exists())


if __name__ == '__main__':
    unittest.main()
