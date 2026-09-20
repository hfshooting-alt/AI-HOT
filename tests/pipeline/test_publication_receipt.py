import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from automation import publication_receipt as receipt, recovery

ROOT = Path(__file__).resolve().parents[2]


class PublicationReceiptTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'web/public').mkdir(parents=True)
        env = patch.dict(os.environ, {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '100',
                                     'GITHUB_RUN_ATTEMPT': '2', 'PRIVATE_KEY': 'PRIVATE-KEY'}, clear=True)
        env.start(); self.addCleanup(env.stop)

    def test_receipt_binds_final_data_commit_and_hashes_only(self):
        for name in receipt.PUBLIC_FILES:
            (self.root / name).write_text('PRIVATE-BODY-OR-MODEL-RESPONSE', encoding='utf-8')
        pending = receipt.write_receipt(self.root, 'b' * 40, 'pending')
        accepted = receipt.write_receipt(self.root, 'b' * 40, 'accepted')
        self.assertEqual(pending['pagesDispatch']['status'], 'pending')
        self.assertEqual(accepted['pagesDispatch']['status'], 'accepted')
        self.assertEqual(accepted['codeSha'], 'a' * 40)
        self.assertEqual(accepted['dataCommitSha'], 'b' * 40)
        self.assertEqual(accepted['githubRunAttempt'], 2)
        self.assertEqual(accepted['publicFileSha256']['web/public/snapshot.json'],
                         hashlib.sha256(b'PRIVATE-BODY-OR-MODEL-RESPONSE').hexdigest())
        self.assertFalse(accepted['manualReviewEvidence']['provesCurrentDailyResearch'])
        self.assertTrue(accepted['manualReviewEvidence']['mayBeHistorical'])
        saved = (self.root / receipt.OUTPUT).read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE', saved)
        self.assertNotIn('runId', accepted['pagesDispatch'])
        self.assertFalse(accepted['pagesDispatch']['deploymentVerified'])
        self.assertNotIn('deploymentSucceeded', accepted)

    def test_failed_dispatch_does_not_erase_successful_push(self):
        result = receipt.write_receipt(self.root, 'b' * 40, 'failed')
        self.assertTrue(result['pushSucceeded'])
        self.assertEqual(result['pagesDispatch']['status'], 'failed')
        self.assertEqual(result['dataCommitSha'], 'b' * 40)

    def test_invalid_sha_or_deployment_claim_rejected(self):
        for sha, status in [('short', 'accepted'), ('b' * 40, 'deployed')]:
            with self.subTest(sha=sha, status=status), self.assertRaises(ValueError):
                receipt.write_receipt(self.root, sha, status)
        self.assertFalse((self.root / receipt.OUTPUT).exists())

    def test_write_failure_is_explicit_nonzero_and_sanitized(self):
        with patch('sys.argv', ['receipt', '--data-sha', 'b' * 40, '--pages-dispatch', 'accepted']), \
                patch.object(receipt, 'write_receipt', side_effect=OSError('PRIVATE-ERROR')), \
                patch('sys.stderr', new_callable=io.StringIO) as output:
            code = receipt.main()
        self.assertEqual(code, 1)
        self.assertIn('回执写入失败', output.getvalue())
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_receipt_and_schedule_diagnostic_survive_encrypted_recovery(self):
        receipt.write_receipt(self.root, 'b' * 40, 'accepted')
        (self.root / 'work/schedule-audit.json').write_text('{"status":"available"}')
        bundle = self.root / 'work/recovery.bin'
        key = 'offline-fixture-secret-for-recovery'
        recovery.pack(self.root, bundle, key)
        restored = recovery.unpack(self.root, bundle, key)
        self.assertEqual((restored / receipt.OUTPUT).read_bytes(), (self.root / receipt.OUTPUT).read_bytes())
        self.assertTrue((restored / 'work/schedule-audit.json').exists())

    def test_workflow_records_after_push_and_distinguishes_dispatch_outcomes(self):
        workflow = (ROOT / '.github/workflows/fetch-manus.yml').read_text(encoding='utf-8')
        block = next(b for b in re.split(r'\n      - ', workflow) if 'git push\n' in b)
        self.assertLess(block.index('git push\n'), block.index('git rev-parse HEAD'))
        self.assertLess(block.index('record_receipt pending'), block.index('if gh workflow run'))
        self.assertIn('then\n            record_receipt accepted\n          else', block)
        self.assertIn('record_receipt failed\n            exit 1', block)
        # Bash -e must not let a diagnostic write prevent the real dispatch.
        wrapper = block.split('record_receipt() {', 1)[1].split('\n          }', 1)[0]
        self.assertIn('if ! PYTHONPATH=scripts python -m automation.publication_receipt', wrapper)
        self.assertIn('--pages-dispatch "$1"; then', wrapper)
        self.assertIn('echo "::warning::', wrapper)
        self.assertNotIn('exit ', wrapper)
        status = next(b for b in re.split(r'\n      - ', workflow) if 'name: pipeline-status-' in b)
        self.assertIn('work/publication-receipt.json', status)
        self.assertIn('work/schedule-audit.json', status)


if __name__ == '__main__':
    unittest.main()
