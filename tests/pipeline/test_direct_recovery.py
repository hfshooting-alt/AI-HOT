"""Recovery only requests selected details and cannot move windows or erase evidence."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from direct_source.collector import collect
from direct_source.health import summarize
from direct_source.recovery import recover
from .test_direct_platforms import SOURCE, WINDOW, OBSERVED, txrow, page, detail


class RecordingFake:
    def __init__(self, directory, *, rows, failure=None, missing_body=False, **kwargs):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.rows, self.failure, self.missing_body = rows, failure, missing_body
        self.count, self.calls = 0, []

    def __call__(self, url, *, method='GET', data=None):
        self.count += 1
        self.calls.append(url)
        stem = self.directory / f'{self.count:04d}'
        receipt = {'url': url, 'method': method, 'observedAt': OBSERVED, 'redirectHop': 0}
        if self.failure and url == self.rows[-1]['url']:
            receipt.update(errorType='TimeoutError')
            if isinstance(self.failure, int):
                receipt['httpStatus'] = self.failure
            stem.with_suffix('.json').write_text(json.dumps(receipt), encoding='utf-8')
            raise TimeoutError()
        text = (json.dumps(page(self.rows), ensure_ascii=False) if 'getSubNewsMixedList' in url
                else detail(next(r for r in self.rows if r['url'] == url), body=None) if self.missing_body
                else detail(next(r for r in self.rows if r['url'] == url)))
        raw = text.encode()
        receipt.update(httpStatus=200, sha256=hashlib.sha256(raw).hexdigest(), charset='utf-8')
        stem.with_suffix('.body').write_bytes(raw)
        stem.with_suffix('.json').write_text(json.dumps(receipt), encoding='utf-8')
        return {**receipt, 'text': text, 'receipt': str(stem.with_suffix('.json'))}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.groups = {'group_a': [SOURCE]}
        self.rows = [txrow(), txrow('20260923A0000200', title='文章二')]
        self.live = []

    def original(self, failure=True, missing_body=False):
        collect(WINDOW, self.root / 'original', groups=self.groups,
                fetch_factory=lambda p: RecordingFake(p, rows=self.rows, failure=failure, missing_body=missing_body))
        return self.root / 'original/collection.json'

    def factory(self, path, **kwargs):
        fake = RecordingFake(path, rows=self.rows, **kwargs)
        self.live.append(fake)
        return fake

    def run_recovery(self, path, urls=None):
        return recover(path, SOURCE['account_name'], urls or [self.rows[-1]['url']], self.root / 'recovery',
                       fetch_factory=self.factory, groups=self.groups)

    def test_selected_failure_only_and_original_success_is_unchanged(self):
        path = self.original()
        before = path.read_bytes()
        original = json.loads(before)
        candidate = self.run_recovery(path)
        self.assertEqual(self.live[0].calls, [self.rows[-1]['url']])
        self.assertEqual(candidate['collectionWindow'], WINDOW)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(candidate['sources'][0]['items']), 2)
        self.assertEqual(candidate['sources'][0]['items'][0], original['sources'][0]['items'][0])
        self.assertFalse(candidate['sources'][0]['health']['exposedFeedComplete'])
        self.assertEqual(candidate['sources'][0]['health']['detailFailures'], 0)
        with self.assertRaises(ValueError):
            self.run_recovery(path)

    def test_successful_or_unseen_url_cannot_be_refetched(self):
        path = self.original()
        for url in (self.rows[0]['url'], 'https://news.qq.com/rain/a/20260923A9999900'):
            with self.assertRaises(ValueError):
                self.run_recovery(path, [url])
        self.assertEqual(self.live, [])

    def test_access_restricted_does_not_retry(self):
        path = self.original(failure=403)
        with self.assertRaises(ValueError):
            self.run_recovery(path)
        self.assertEqual(self.live, [])

    def test_missing_body_recovered_without_relisting_network(self):
        candidate = self.run_recovery(self.original(failure=False, missing_body=True))
        self.assertEqual(self.live[0].calls, [self.rows[-1]['url']])
        self.assertEqual(candidate['sources'][0]['health']['awaitingBodies'], 1)

    def test_tampered_list_never_causes_network_or_loses_success(self):
        path = self.original()
        body = next(path.parent.glob('*/http/0001.body'))
        body.write_bytes(b'tampered')
        candidate = self.run_recovery(path)
        self.assertEqual(self.live[0].calls, [])
        self.assertEqual(len(candidate['sources'][0]['items']), 1)
        self.assertEqual(candidate['sources'][0]['recovery']['verified'], [])

    def test_outside_original_window_cannot_be_admitted(self):
        path = self.original()
        self.rows[-1]['time'] = '2026-09-24 12:00:00'
        candidate = self.run_recovery(path)
        self.assertEqual(len(candidate['sources'][0]['items']), 1)
        self.assertEqual(candidate['sources'][0]['recovery']['verified'], [])

    def test_health_distinguishes_empty_failure_and_partial_coverage(self):
        base = {'items': [], 'status': 'partial', 'coverage': {}}
        self.assertEqual(summarize(base)['state'], 'no_verified_samples_coverage_incomplete')
        self.assertEqual(summarize({**base, 'status': 'failed'})['state'], 'source_failed')
        self.assertEqual(summarize({**base, 'status': 'complete', 'coverage': {'coverageComplete': True}})['state'],
                         'no_articles_in_exposed_feed_window')
        self.assertEqual(summarize({**base, 'diagnostics': [{'stage': 'detail', 'reason': 'TimeoutError'}]})['state'],
                         'partial_failure')

    def test_stale_failure_does_not_override_reviewed_success_or_enable_retry(self):
        path = self.original(failure=False)
        data = json.loads(path.read_text(encoding='utf-8'))
        result = data['sources'][0]
        result['diagnostics'] = [{'stage': 'detail', 'url': self.rows[-1]['url'], 'reason': 'detail_title_mismatch'}]
        health = summarize(result)
        self.assertEqual(health['state'], 'verified_articles')
        self.assertEqual(health['detailFailures'], 0)
        self.assertEqual(health['historicalDetailFailuresResolved'], 1)
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_recovery(path)
        self.assertEqual(self.live, [])


if __name__ == '__main__':
    unittest.main()
