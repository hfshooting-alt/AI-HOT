import json
from pathlib import Path
import tempfile
import unittest

from automation.run_summary import render
from automation.runner import tree_digest


class RunSummaryTests(unittest.TestCase):
    def fixture(self, root, published=True):
        window = {'start': '2026-09-21T09:30:00+08:00', 'end': '2026-09-22T09:30:00+08:00'}
        state = root / 'work/runs/2026-09-22/ten-am/test/state.json'
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({'published': published, 'collectionWindow': window,
                                     'stages': {'content': {'status': 'failed', 'exitCode': -6}}}), encoding='utf-8')
        snapshot = root / 'web/public/snapshot.json'
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text(json.dumps({'collectionWindow': window, 'collectionStatus': {'degraded': True},
                                        'all': {'items': [{'id': 'aihot:one'}]}}), encoding='utf-8')
        payload = json.loads(state.read_text(encoding='utf-8'))
        payload['publishedOutputs'] = {'web/public': tree_digest(root / 'web/public')}
        state.write_text(json.dumps(payload), encoding='utf-8')

    def test_published_partial_batch_discloses_native_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            result = render(root)
            self.assertIn('| content | failed | -6 |', result)
            self.assertIn('AIHOT 1 条；Manus 0 条', result)
            self.assertIn('来源覆盖不完整', result)

    def test_unpublished_does_not_report_old_snapshot_as_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root, published=False)
            self.assertNotIn('本批新闻', render(root))

    def test_direct_legacy_and_unknown_collectors_are_counted_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            snapshot_path = root / 'web/public/snapshot.json'
            snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
            snapshot['all']['items'] = [
                {'id': 'direct:new', 'collector': 'direct_site'},
                {'id': 'manus:legacy'}, {'id': 'manus:current', 'collector': 'manus'},
                {'id': 'aihot:legacy'}, {'id': 'other:unknown'},
                {'id': 'direct:no-collector'}, {'id': 'manus:conflict', 'collector': 'direct_site'},
                {'id': 'manus:'},
            ]
            snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
            state_path = next((root / 'work/runs').glob('*/ten-am/*/state.json'))
            state = json.loads(state_path.read_text(encoding='utf-8'))
            state['stages']['direct'] = {'status': 'success', 'exitCode': 0}
            state['publishedOutputs'] = {'web/public': tree_digest(root / 'web/public')}
            state_path.write_text(json.dumps(state), encoding='utf-8')
            result = render(root)
            self.assertIn('新闻Daily：运行与发布结果', result)
            self.assertIn('| direct | success | 0 |', result)
            self.assertIn('AIHOT 1 条；Manus 2 条；网站直采 1 条；来源未确认 4 条', result)

    def test_missing_state_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn('没有本轮阶段记录', render(Path(folder)))

    def test_same_window_newer_data_is_not_attributed_to_old_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            p = root / 'web/public/snapshot.json'
            value = json.loads(p.read_text(encoding='utf-8'))
            value['all']['items'].append({'id': 'manus:later'})
            p.write_text(json.dumps(value), encoding='utf-8')
            self.assertNotIn('本批新闻', render(root))

    def test_invalid_stage_records_remain_unknown(self):
        for payload in ([], {'stages': None}, {'stages': {'content': None}}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.fixture(root)
                state = next((root / 'work/runs').glob('*/ten-am/*/state.json'))
                state.write_text(json.dumps(payload), encoding='utf-8')
                self.assertNotIn('本批新闻', render(root))
