import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from manus_source.client import ManusClient, CreatedTask, ManusAPIError
from manus_source.config import load_sources
from manus_source.runner import (run_discovery, render_discovery_prompt, source_seed_prompt,
                                 run_discovery_with_receipt, DiscoveryRunError)

ROOT = Path(__file__).resolve().parents[2]
WINDOW = {'start': '2026-09-21T09:30:00+08:00', 'end': '2026-09-22T09:30:00+08:00',
          'timezone': 'Asia/Shanghai'}


class Captured(Exception):
    pass


class IncrementalTest(unittest.TestCase):
    def setUp(self):
        guard = patch.dict(os.environ, {'AIHOT_CUTOFF_TIME': '09:30'})
        guard.start()
        self.addCleanup(guard.stop)

    def test_actual_create_payload_for_all_twenty_sources(self):
        groups = load_sources(ROOT / 'config/manus_sources.json')
        self.assertEqual(sum(map(len, groups.values())), 20)
        for group, sources in groups.items():
            for source in sources:
                with self.subTest(source=source['account_name']):
                    sent = []
                    def capture(method, path, payload):
                        self.assertEqual((method, path), ('POST', 'task.create'))
                        sent.append(payload)
                        raise Captured()
                    client = ManusClient('offline', 'manus-1.6', 0, 1,
                                         transport=capture, inline_prompt=True, create_retries=0)
                    prompt = render_discovery_prompt(ROOT / 'scripts/prompts/manus_discovery_incremental.md', [source])
                    prompt = prompt.replace('{{WINDOW_START}}', WINDOW['start']).replace('{{WINDOW_END}}', WINDOW['end'])
                    with self.assertRaises(Captured):
                        run_discovery(client, group, '2026-09-22', prompt, [source['account_name']],
                                      WINDOW, 20, [source])
                    self.assertEqual(len(sent), 1)
                    content = sent[0]['message']['content']
                    self.assertEqual([c['type'] for c in content], ['text'])
                    text = content[0]['text']
                    for required in (source['account_name'], source['home_url'], WINDOW['start'], WINDOW['end'], 'AIHOT_ARTICLE'):
                        self.assertIn(required, text)
                    self.assertNotIn('{{', text)
                    if source['platform'] != 'Official Jiqizhixin':
                        self.assertNotIn('机器之心', text)
                    props = sent[0]['structured_output_schema']['properties']['articles']['items']
                    self.assertEqual(set(props['required']), set(props['properties']))

    def test_seed_prompt_is_bounded_and_not_full_trace(self):
        seed = {'status': 'available', 'hintOnly': True, 'coverageComplete': False,
                'observations': [{'private': 'raw'}] * 100,
                'candidates': [{'title': str(i), 'url': 'https://www.baijing.cn/article/1'} for i in range(20)]}
        text = source_seed_prompt(seed)
        data = json.loads(text.split('\n')[-1])
        self.assertEqual(len(data['candidates']), 2)
        self.assertEqual(data['additionalCandidatesOmitted'], 18)
        self.assertNotIn('observations', data)
        self.assertFalse(data['coverageComplete'])

    def test_diagnostic_failure_preserves_successful_collection(self):
        client = ManusClient('offline', 'manus-1.6', 0, 1, diagnostics_dir=ROOT / 'work')
        result = {'articles': []}
        def collect(client, *args):
            client._receipt_context.callback({'taskId': 't', 'terminalConfirmed': True})
            return result
        with patch('manus_source.runner.run_discovery', side_effect=collect), \
             patch('manus_source.diagnostics.capture_task_diagnostics', side_effect=OSError()):
            self.assertIs(run_discovery_with_receipt(client, (), lambda _: None), result)

    def test_late_article_is_recovered_only_after_confirmed_stop(self):
        source = {'account_name': 'Test', 'platform': 'Website', 'home_url': 'https://example.com/'}
        article = {'account_name': 'Test', 'source_platform': 'Website', 'source_home_url': source['home_url'],
                   'article_url': 'https://example.com/1', 'title': 'Original article',
                   'published_at': '2026-09-21T15:00:00+08:00', 'published_date': '2026-09-21',
                   'published_time_text': None, 'author': None, 'extraction_status': 'complete', 'note': None}
        for confirmed in (True, False):
            client = ManusClient('offline', 'manus-1.6', 0, 1, late_result_grace_seconds=15)
            with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
                 patch.object(client, 'wait_for_structured_result', side_effect=ManusAPIError('credit limit')), \
                 patch.object(client, 'stop_task'), \
                 patch.object(client, 'confirm_task_stopped', return_value={'confirmed': confirmed, 'remoteStatus': 'stopped' if confirmed else 'running'}), \
                 patch.object(client, 'read_stopped_results', side_effect=[None, {'articles': [article]}]) as read, \
                 patch('manus_source.runner.time.sleep') as sleep:
                with self.assertRaises(DiscoveryRunError) as caught:
                    run_discovery(client, 'group_a', '2026-09-22', 'prompt', ['Test'], WINDOW, 20, [source])
                self.assertEqual(read.call_count, 2 if confirmed else 1)
                self.assertEqual(sleep.call_count, int(confirmed))
                self.assertEqual(bool(caught.exception.partial_payload), confirmed)
                self.assertEqual(client._creation_blocked.is_set(), not confirmed)

    def test_late_complete_empty_final_passes_normal_contract_validation(self):
        source = {'account_name': 'Test', 'platform': 'Website', 'home_url': 'https://example.com/'}
        final = {'source_group': 'group_a', 'target_date': '2026-09-22', 'articles': [],
                 'source_audits': [{'account_name': 'Test', 'source_status': 'complete',
                                    'article_count': 0, 'note': 'Verified old boundary'}]}
        client = ManusClient('offline', 'manus-1.6', 0, 1, late_result_grace_seconds=15)
        with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
             patch.object(client, 'wait_for_structured_result', side_effect=ManusAPIError('credit limit')), \
             patch.object(client, 'stop_task'), \
             patch.object(client, 'confirm_task_stopped', return_value={'confirmed': True, 'remoteStatus': 'stopped'}), \
             patch.object(client, 'read_stopped_results', side_effect=[None, final]), \
             patch('manus_source.runner.time.sleep'):
            result = run_discovery(client, 'group_a', '2026-09-22', 'prompt', ['Test'], WINDOW, 20, [source])
        self.assertEqual(result['source_audits'][0]['source_status'], 'complete')
        self.assertEqual(result['collectionWindow'], WINDOW)

    def test_structured_result_does_not_release_worker_before_terminal_confirmation(self):
        source = {'account_name': 'Test', 'platform': 'Website', 'home_url': 'https://example.com/'}
        article = {'account_name': 'Test', 'source_platform': 'Website', 'source_home_url': source['home_url'],
                   'article_url': 'https://example.com/1', 'title': 'Original article',
                   'published_at': '2026-09-21T15:00:00+08:00', 'published_date': '2026-09-21',
                   'published_time_text': None, 'author': None, 'extraction_status': 'complete', 'note': None}
        final = {'source_group': 'group_a', 'target_date': '2026-09-22', 'articles': [article],
                 'source_audits': [{'account_name': 'Test', 'source_status': 'complete', 'article_count': 1, 'note': None}]}
        for stopped in (True, False):
            client = ManusClient('offline', 'manus-1.6', 0, 1, require_terminal_confirmation=True)
            with patch.object(client, 'create_crawl_task', return_value=CreatedTask('t', 'https://example.com/t')), \
                 patch.object(client, 'wait_for_structured_result', return_value=final), \
                 patch.object(client, 'stop_task') as stop, \
                 patch.object(client, 'confirm_task_stopped', side_effect=[
                     {'confirmed': False, 'remoteStatus': 'running'},
                     {'confirmed': stopped, 'remoteStatus': 'stopped' if stopped else 'running'}]), \
                 patch.object(client, 'read_stopped_results', return_value=None):
                if stopped:
                    result = run_discovery(client, 'group_a', '2026-09-22', 'prompt', ['Test'], WINDOW, 20, [source])
                    self.assertEqual(len(result['articles']), 1)
                    self.assertEqual(result['source_audits'][0]['source_status'], 'complete')
                else:
                    with self.assertRaises(DiscoveryRunError) as caught:
                        run_discovery(client, 'group_a', '2026-09-22', 'prompt', ['Test'], WINDOW, 20, [source])
                    self.assertEqual(len(caught.exception.partial_payload['articles']), 1)
                stop.assert_called_once_with('t')
                self.assertEqual(client._creation_blocked.is_set(), not stopped)
