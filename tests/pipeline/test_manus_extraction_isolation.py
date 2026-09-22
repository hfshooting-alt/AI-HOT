import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from manus_source import crawler


def result(code=0, value=None):
    return SimpleNamespace(returncode=code, stdout=json.dumps(
        value or {'text': 'good body ' * 30, 'title': 'Article'}).encode(),
        stderr=b'private body or credential must never be printed')


class NativeExtractionIsolationTests(unittest.TestCase):
    def test_worker_process_arguments_are_private_bounded_and_metadata_aware(self):
        with patch.dict(os.environ, {'MANUS_API_KEY': 'secret', 'LLM_API_KEY': 'secret'}), \
                patch.object(crawler.subprocess, 'run', return_value=result()) as run:
            text, title = crawler.extract_text(b'<p>body</p>', timeout_seconds=7)
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(command[:2], [sys.executable, '-I'])
        self.assertTrue(command[2].endswith('extraction_worker.py'))
        self.assertEqual(command[3:], ['--metadata'])
        self.assertEqual(kwargs['input'], b'<p>body</p>')
        self.assertEqual(kwargs['timeout'], 7)
        self.assertNotIn('MANUS_API_KEY', kwargs['env'])
        self.assertNotIn('LLM_API_KEY', kwargs['env'])
        self.assertNotIn('shell', kwargs)
        self.assertEqual(title, 'Article')

    def test_head_title_priority_does_not_require_native_metadata(self):
        with patch.object(crawler, '_run_extraction', return_value=result()) as run:
            _, title = crawler.extract_text(b'<head><title>Expected</title></head>')
        self.assertEqual(title, 'Expected')
        self.assertFalse(run.call_args.args[2])

    def test_worker_abort_becomes_failed_article_and_other_parallel_article_survives(self):
        articles = [{'account_name': 'Test', 'article_url': f'https://example.com/{name}',
                     'title': 'Article', 'published_date': '2026-09-22'} for name in ('bad', 'good')]
        def worker(html, timeout, metadata):
            return result(-6 if html == b'bad' else 0)
        with patch.object(crawler, '_run_extraction', side_effect=worker):
            batch = crawler.crawl_batch(articles, '2026-09-22', concurrency=2,
                transport=lambda url, headers: (url, url.rsplit('/', 1)[-1].encode()))
        bad, good = batch['articles']
        self.assertEqual(bad['content_status'], 'failed')
        self.assertIn('exit=-6', bad['note'])
        self.assertEqual(bad['content_text'], '')
        self.assertNotIn('private', bad['note'])
        self.assertEqual(good['content_status'], 'complete')
        self.assertEqual([a['article_url'] for a in batch['articles']], [a['article_url'] for a in articles])

    def test_timeout_does_not_retry_extraction_or_fetch(self):
        article = {'account_name': 'Test', 'article_url': 'https://example.com/1',
                   'title': 'Article', 'published_date': '2026-09-22'}
        with patch.object(crawler, '_run_extraction', side_effect=subprocess.TimeoutExpired('worker', 2)) as run:
            value = crawler.crawl_one(article, '2026-09-22', timeout_seconds=2,
                                       transport=lambda url, headers: (url, b'html'))
        run.assert_called_once()
        self.assertEqual(value['content_status'], 'failed')
        self.assertIn('超时', value['note'])

    def test_invalid_worker_output_and_oversize_are_rejected_without_exposing_it(self):
        for stdout in (b'private non-json', b'[]', b'{"text":7,"title":null}',
                       b'x' * (crawler.MAX_EXTRACTION_OUTPUT_BYTES + 1)):
            with self.subTest(size=len(stdout)), patch.object(crawler, '_run_extraction',
                    return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr=b'')):
                with self.assertRaises(crawler.CrawlError) as error:
                    crawler.extract_text(b'html')
                self.assertNotIn('private', str(error.exception))
        with patch.object(crawler, '_run_extraction') as run:
            with self.assertRaises(crawler.CrawlError):
                crawler.extract_text(b'x' * (crawler.MAX_EXTRACTION_INPUT_BYTES + 1))
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
