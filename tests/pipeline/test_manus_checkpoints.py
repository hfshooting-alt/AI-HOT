import json
from datetime import datetime
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from manus_source.checkpoints import (accept_article, checkpoint_articles, partial_payload,
                                     normalize_article_time, publication_time_conflict)
from manus_source.client import ManusClient, ManusAPIError, CreatedTask
from manus_source.client import validate_output_schema
from manus_source.runner import run_discovery, DiscoveryRunError

WINDOW = {'start': '2026-09-13T09:30:00+08:00', 'end': '2026-09-14T09:30:00+08:00', 'timezone': 'Asia/Shanghai'}
SOURCE = {'account_name': 'Test', 'platform': 'Website', 'home_url': 'https://example.com/news'}
ARTICLE = {'account_name': 'Test', 'source_platform': 'Website', 'source_home_url': SOURCE['home_url'],
    'article_url': 'https://example.com/article', 'title': 'Verified article',
    'published_date': '2026-09-14', 'published_at': '2026-09-14T08:00:00+08:00',
    'extraction_status': 'complete', 'author': None, 'note': None}


class CheckpointTest(unittest.TestCase):
    def test_explicit_publication_conflict_cannot_use_yesterday_exception(self):
        raw = {**ARTICLE, 'published_time_text': '昨天',
               'note': '详情页同时显示“2026-09-12 19:04发布于广东”，与列表相对时间不一致；published_at置空。'}
        normalized = normalize_article_time(raw, datetime.fromisoformat('2026-09-14T10:00:00+08:00'))
        self.assertTrue(publication_time_conflict(normalized))
        self.assertFalse(accept_article(normalized, 'group_a', '2026-09-14', ['Test'], WINDOW, [SOURCE]))
        for note in ('详情页2026-09-12 19:04评论，与列表不一致',
                     'URL为20260912，不能作发布时间；昨天已核实',
                     '昨天发布；署名与账号显示名称不一致',
                     '详情2026-09-13 19:04发布；署名与账号显示名称不一致'):
            with self.subTest(note=note):
                self.assertFalse(publication_time_conflict({**normalized, 'note': note}))

    def test_unconfirmed_stop_blocks_next_create_but_keeps_checkpoint(self):
        client = ManusClient('test', 'manus-1.6', 0, 1, create_retries=0)
        def wait(task_id, **kwargs):
            kwargs['on_checkpoint'](ARTICLE)
            raise ManusAPIError('Observed credit threshold reached: 20 >= 20')
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=wait), \
             patch.object(client, 'stop_task'), \
             patch.object(client, 'read_stopped_results', return_value={'articles': None}), \
             patch.object(client, 'confirm_task_stopped', return_value={
                 'confirmed': False, 'remoteStatus': 'running', 'error': 'stop unconfirmed'}):
            with self.assertRaises(DiscoveryRunError) as caught:
                run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'], WINDOW, 20, [SOURCE])
        self.assertTrue(caught.exception.stop_accepted)
        self.assertFalse(caught.exception.stop_succeeded)
        self.assertEqual(caught.exception.remote_status, 'running')
        self.assertEqual(caught.exception.partial_payload['articles'], [ARTICLE])
        with patch.object(client, 'transport') as transport:
            with self.assertRaisesRegex(ManusAPIError, 'task not created'):
                client.create_crawl_task('p', 'g', 'd', 't', 'b')
        transport.assert_not_called()

    def test_later_publication_conflict_revokes_earlier_checkpoint(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        conflict = {**ARTICLE, 'published_time_text': '昨天',
                    'note': '详情2026-09-12 19:04发布，与列表昨天不一致。'}
        def finish(task_id, **kwargs):
            kwargs['on_checkpoint'](ARTICLE)
            return {'source_group': 'group_a', 'target_date': '2026-09-14',
                    'articles': [conflict], 'source_audits': [{'account_name': 'Test',
                    'article_count': 1, 'source_status': 'complete', 'note': None}]}
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=finish):
            result = run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'],
                                   WINDOW, source_specs=[SOURCE])
        self.assertEqual(result['articles'], [])
        self.assertEqual(result['source_audits'][0]['source_status'], 'failed')

    def test_malformed_time_keeps_checkpoint_but_downgrades_coverage(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        def finish(task_id, **kwargs):
            kwargs['on_checkpoint'](ARTICLE)
            return {'source_group': 'group_a', 'target_date': '2026-09-14',
                    'articles': [{**ARTICLE, 'published_at': 'invalid'}],
                    'source_audits': [{'account_name': 'Test', 'article_count': 1,
                                       'source_status': 'complete', 'note': None}]}
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=finish):
            result = run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'],
                                   WINDOW, source_specs=[SOURCE])
        self.assertEqual(result['articles'], [ARTICLE])
        self.assertEqual(result['source_audits'][0]['source_status'], 'partial')

    def test_repeated_relative_time_preserves_first_local_observation(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        raw = {**ARTICLE, 'published_at': None, 'published_date': None,
               'published_time_text': '昨天'}
        observed = datetime.fromisoformat('2026-09-14T10:00:00+08:00')
        normalized = normalize_article_time(raw, observed)
        def finish(task_id, **kwargs):
            kwargs['on_checkpoint'](raw)
            kwargs['on_checkpoint'](raw)
            return {'source_group': 'group_a', 'target_date': '2026-09-14',
                    'articles': [raw], 'source_audits': [{'account_name': 'Test',
                    'article_count': 1, 'source_status': 'complete', 'note': None}]}
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=finish), \
             patch('manus_source.checkpoints.normalize_article_time', return_value=normalized) as normalize:
            result = run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'],
                                   WINDOW, source_specs=[SOURCE])
        normalize.assert_called_once_with(raw)
        self.assertEqual(result['articles'], [normalized])

    def test_later_absolute_time_replaces_checkpoint_and_rechecks_window(self):
        for latest_time, accepted in [('2026-09-14T08:15:00+08:00', True),
                                      ('2026-09-12T08:00:00+08:00', False)]:
            with self.subTest(latest_time=latest_time):
                client = ManusClient('test', 'manus-1.6', 0, 1)
                corrected = {**ARTICLE, 'published_at': latest_time,
                             'published_date': latest_time[:10], 'published_time_text': None}
                def finish(task_id, **kwargs):
                    kwargs['on_checkpoint']({**ARTICLE, 'published_time_text': None})
                    return {'source_group': 'group_a', 'target_date': '2026-09-14',
                            'articles': [corrected], 'source_audits': [{'account_name': 'Test',
                            'article_count': 1, 'source_status': 'complete', 'note': None}]}
                with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
                     patch.object(client, 'wait_for_structured_result', side_effect=finish):
                    result = run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'],
                                           WINDOW, source_specs=[SOURCE])
                self.assertEqual(result['articles'], [corrected] if accepted else [])
                self.assertEqual(result['source_audits'][0]['source_status'],
                                 'complete' if accepted else 'failed')

    def test_final_metadata_does_not_erase_checkpoint_body(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        def finish(task_id, **kwargs):
            kwargs['on_checkpoint']({**ARTICLE, 'content_text': 'body', 'content_title': ARTICLE['title']})
            return {'source_group': 'group_a', 'target_date': '2026-09-14',
                    'articles': [ARTICLE], 'source_audits': [{'account_name': 'Test',
                    'article_count': 1, 'source_status': 'complete', 'note': None}]}
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=finish):
            result = run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'], WINDOW,
                                   source_specs=[SOURCE])
        self.assertEqual(result['articles'][0]['content_text'], 'body')

    def test_jiqizhixin_body_handoff_schema_passes_preflight(self):
        source = {'account_name': '机器之心', 'platform': 'Official Jiqizhixin',
                  'home_url': 'https://jigou.jiqizhixin.com/industry'}
        client = Mock()
        client.create_crawl_task.return_value = CreatedTask('test', 'https://example.com/test')
        client.wait_for_structured_result.return_value = {
            'source_group': 'group_a', 'target_date': '2026-09-14', 'articles': [],
            'source_audits': [{'account_name': '机器之心', 'article_count': 0,
                              'source_status': 'complete', 'note': None}]}
        run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['机器之心'], WINDOW,
                      source_specs=[source])
        schema = client.create_crawl_task.call_args.kwargs['output_schema']
        validate_output_schema(schema)
        self.assertIn('content_text', schema['properties']['articles']['items']['required'])
        self.assertIn('content_title', schema['properties']['articles']['items']['required'])

    def test_jiqizhixin_accepts_missing_author_but_not_other_publishers(self):
        source = {'account_name': '机器之心', 'platform': 'Official Jiqizhixin',
                  'home_url': 'https://jigou.jiqizhixin.com/industry'}
        article = {**ARTICLE, 'account_name': '机器之心',
                   'source_platform': source['platform'], 'source_home_url': source['home_url'],
                   'article_url': 'https://jigou.jiqizhixin.com/articles/test'}
        for author in ('ScienceAI', '新闻资讯'):
            self.assertFalse(accept_article({**article, 'author': author}, 'group_a',
                '2026-09-14', ['机器之心'], WINDOW, [source]))
        self.assertTrue(accept_article({**article, 'author': '机器之心'}, 'group_a',
            '2026-09-14', ['机器之心'], WINDOW, [source]))
        self.assertTrue(accept_article({**article, 'author': None}, 'group_a',
            '2026-09-14', ['机器之心'], WINDOW, [source]))

    def test_malformed_final_envelope_keeps_prior_checkpoint(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        def finish(task_id, **kwargs):
            kwargs['on_checkpoint'](ARTICLE)
            return {'articles': None}
        with patch.object(client,'create_crawl_task',return_value=CreatedTask('t','https://example.com/t')), \
             patch.object(client,'wait_for_structured_result',side_effect=finish):
            result=run_discovery(client,'group_a','2026-09-14','prompt',['Test'],WINDOW,20,[SOURCE])
        self.assertEqual(result['articles'],[ARTICLE])
        self.assertEqual(result['source_audits'][0]['source_status'],'partial')

    def test_bad_final_article_between_good_ones_does_not_drop_either(self):
        second={**ARTICLE,'article_url':'https://example.com/second'}
        value={'source_group':'group_a','target_date':'2026-09-14','articles':[ARTICLE,None,second],
               'source_audits':[{'account_name':'Test','source_status':'complete','article_count':3,'note':None}]}
        client=Mock()
        client.create_crawl_task.return_value=CreatedTask('t','https://example.com/t')
        client.wait_for_structured_result.return_value=value
        result=run_discovery(client,'group_a','2026-09-14','prompt',['Test'],WINDOW,20,[SOURCE])
        self.assertEqual(result['articles'],[ARTICLE,second])
        self.assertEqual(result['source_audits'][0]['source_status'],'partial')
    def test_final_text_result_can_be_recovered_as_unverified_candidates(self):
        response={'messages':[{'type':'assistant_message','assistant_message':{
            'delivery_kind':'result','content':json.dumps({'articles':[ARTICLE, None]})}}]}
        self.assertEqual(list(checkpoint_articles(response)), [ARTICLE])
        self.assertFalse(accept_article({**ARTICLE,'title':42},'group_a','2026-09-14',['Test'],WINDOW,[SOURCE]))
    def test_joined_progress_records_with_trailing_prose_are_recovered(self):
        second = {**ARTICLE, 'article_url': 'https://example.com/second'}
        text = 'AIHOT_ARTICLE ' + json.dumps(ARTICLE) + 'AIHOT_ARTICLE ' + json.dumps(second) + '已核实两篇'
        response = {'messages':[{'type':'assistant_message','assistant_message':{'content':text}}]}
        recovered = list(checkpoint_articles(response))
        self.assertEqual(recovered, [ARTICLE, second])
        self.assertTrue(all(accept_article(a,'group_a','2026-09-14',['Test'],WINDOW,[SOURCE]) for a in recovered))
        response['messages'][0]['assistant_message']['content'] = '只是说明 ' + text
        self.assertEqual(list(checkpoint_articles(response)), [])

    def test_yesterday_is_date_only_and_survives_snapshot(self):
        from manus_source.window import matching_item
        from build_snapshot import build_item
        a = normalize_article_time({**ARTICLE, 'published_at': None, 'published_time_text': '昨天'},
                                   datetime.fromisoformat('2026-09-14T10:00:00+08:00'))
        self.assertEqual(a['published_at'], '2026-09-13')
        self.assertTrue(accept_article(a, 'group_a', '2026-09-14', ['Test'], WINDOW, [SOURCE]))
        item = build_item({**a, 'publishedAt': a['published_at']}, 1, datetime.fromisoformat(WINDOW['end']))
        self.assertTrue(matching_item(WINDOW, item))
        self.assertIn('具体时刻未披露', item['timeText'])
        self.assertNotIn('00:00', item['timeText'])
        wrong = {**item, 'timeEvidence': {**item['timeEvidence'], 'observedAt': '2026-09-15T10:00:00+08:00'}}
        self.assertFalse(matching_item(WINDOW, wrong))

    def test_relative_time_boundary_is_not_claimed_as_precise(self):
        from manus_source.window import matching_item
        for label, accepted in [('5小时前', True), ('1小时前', False)]:
            a = normalize_article_time({**ARTICLE, 'published_time_text': label},
                                       datetime.fromisoformat('2026-09-14T10:00:00+08:00'))
            self.assertEqual(a['publishedPrecision'], 'relative')
            self.assertEqual(matching_item(WINDOW, {**a, 'publishedAt': a['published_at']}), accepted)

    def test_invalid_article_does_not_discard_valid_final_article(self):
        client = ManusClient('test', 'manus-1.6', 0, 1)
        payload = {'articles': [ARTICLE, {**ARTICLE, 'article_url': 'https://example.com/bad', 'published_at': WINDOW['end']}],
                   'source_audits': [{'account_name': 'Test', 'source_status': 'complete', 'article_count': 2, 'note': None}],
                   'target_date': '2026-09-14', 'source_group': 'group_a'}
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', return_value=payload):
            result = run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'], WINDOW, 20, [SOURCE])
        self.assertEqual(result['articles'], [ARTICLE])
        self.assertEqual(result['source_audits'][0]['source_status'], 'partial')
        self.assertEqual(result['source_audits'][0]['article_count'], 1)

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
            on_checkpoint({**ARTICLE, 'article_url': []})
            on_checkpoint({**ARTICLE, 'published_time_text': 42})
            on_checkpoint({**ARTICLE, 'title': 42})
            on_checkpoint(ARTICLE)
            on_checkpoint(ARTICLE)  # Repeated polling must not duplicate articles.
            raise ManusAPIError('Observed credit threshold reached: 20 >= 20')
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=wait), \
             patch.object(client, 'stop_task') as stop, \
             patch.object(client, 'confirm_task_stopped', return_value={'confirmed': True, 'remoteStatus': 'stopped'}), \
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
             patch.object(client, 'confirm_task_stopped', return_value={'confirmed': True, 'remoteStatus': 'stopped'}), \
             patch.object(client, 'read_stopped_results', return_value={'articles': [ARTICLE]}):
            with self.assertRaises(DiscoveryRunError) as caught:
                run_discovery(client, 'group_a', '2026-09-14', 'prompt', ['Test'], WINDOW, 20, [SOURCE])
        self.assertEqual(caught.exception.partial_payload['articles'], [ARTICLE])


if __name__ == '__main__':
    unittest.main()
