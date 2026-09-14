import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from manus_source.checkpoints import accept_article, checkpoint_articles, partial_payload, normalize_article_time
from manus_source.client import ManusClient, ManusAPIError, CreatedTask
from manus_source.runner import run_discovery, DiscoveryRunError

WINDOW = {'start': '2026-09-13T09:30:00+08:00', 'end': '2026-09-14T09:30:00+08:00', 'timezone': 'Asia/Shanghai'}
SOURCE = {'account_name': 'Test', 'platform': 'Website', 'home_url': 'https://example.com/news'}
ARTICLE = {'account_name': 'Test', 'source_platform': 'Website', 'source_home_url': SOURCE['home_url'],
    'article_url': 'https://example.com/article', 'title': 'Verified article',
    'published_date': '2026-09-14', 'published_at': '2026-09-14T08:00:00+08:00',
    'extraction_status': 'complete', 'author': None, 'note': None}


class CheckpointTest(unittest.TestCase):
    def test_chinese_naive_time_is_beijing_without_changing_explicit_instant(self):
        a = {**ARTICLE, 'source_home_url': 'https://news.qq.com/author/example',
             'published_at': '2026-09-14 08:30:00'}
        self.assertEqual(normalize_article_time(a)['published_at'], '2026-09-14T08:30:00+08:00')
        a['published_at'] = '2026-09-14T00:30:00Z'
        self.assertEqual(normalize_article_time(a)['published_at'], '2026-09-14T08:30:00+08:00')
        a['published_at'] = '14小时前'
        self.assertEqual(normalize_article_time(a)['published_at'], '14小时前')

    def setUp(self):
        env = patch.dict(os.environ, {'AIHOT_CUTOFF_TIME': '09:30'})
        env.start()
        self.addCleanup(env.stop)
    def test_accepts_partial_without_claiming_complete_coverage(self):
        p = partial_payload('group_a', '2026-09-14', ['Test'], WINDOW, [ARTICLE], 'boundary unverified')
        self.assertEqual(p['source_audits'][0]['source_status'], 'partial')
        self.assertEqual(p['source_audits'][0]['article_count'], 1)

    def test_rejects_wrong_source_time_and_incomplete_records(self):
        for change in ({'published_at': '2026-09-14T10:00:00+08:00'},
                       {'source_home_url': 'https://other.example/'}, {'title': None}):
            self.assertFalse(accept_article({**ARTICLE, **change}, 'group_a', '2026-09-14', ['Test'], WINDOW, [SOURCE]))
        self.assertTrue(accept_article(ARTICLE, 'group_a', '2026-09-14', ['Test'], WINDOW, [SOURCE]))

    def test_prose_and_user_messages_are_not_checkpoints(self):
        text = 'AIHOT_ARTICLE ' + json.dumps(ARTICLE)
        response = {'messages': [
            {'type': 'user_message', 'user_message': {'content': text}},
            {'type': 'assistant_message', 'assistant_message': {'content': 'Found three articles'}},
            {'type': 'assistant_message', 'assistant_message': {'content': text}},
        ]}
        self.assertEqual(list(checkpoint_articles(response)), [ARTICLE])

    def test_budget_stop_preserves_verified_articles_and_cost_failure(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        def wait(task_id, observed_credit_limit=None, on_checkpoint=None):
            on_checkpoint(ARTICLE)
            on_checkpoint(ARTICLE)  # Repeated polling must not duplicate articles.
            raise ManusAPIError('Observed credit threshold reached: 20 >= 20')
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=wait), \
             patch.object(client, 'stop_task') as stop, \
             patch.object(client, 'read_stopped_results', return_value=None):
            with self.assertRaises(DiscoveryRunError) as caught:
                run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'], WINDOW, 20, [SOURCE])
        stop.assert_called_once_with('t')
        self.assertTrue(caught.exception.stop_succeeded)
        self.assertEqual(caught.exception.partial_payload['articles'], [ARTICLE])
        self.assertIn('Observed credit threshold', str(caught.exception))

    def test_stopped_task_final_result_is_salvaged(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=TimeoutError('timeout')), \
             patch.object(client, 'stop_task'), \
             patch.object(client, 'read_stopped_results', return_value={'articles': [ARTICLE]}):
            with self.assertRaises(DiscoveryRunError) as caught:
                run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'], WINDOW, 20, [SOURCE])
        self.assertEqual(caught.exception.partial_payload['articles'], [ARTICLE])


if __name__ == '__main__':
    unittest.main()
