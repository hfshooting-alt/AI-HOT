"""All collected metadata is published separately from selected investment news."""
import copy
from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import build_snapshot as snapshot
import tag_news


class ArticlePoolSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.previous_taxonomy = snapshot.TAG_TAXONOMY
        snapshot.TAG_TAXONOMY = tag_news.load_taxonomy(str(Path(__file__).resolve().parents[2] / 'config/taxonomy.json'))
        self.now = datetime(2026, 9, 22, 12, tzinfo=snapshot.BJ)
        self.selected = {'id': 'aihot:chosen', 'title': '新模型发布', 'url': 'https://example.org/chosen',
                         'publishedAt': '2026-09-22T08:00:00+08:00', 'summary': '已经审阅的事实摘要。',
                         'classification': {'category': 'release', 'tags': {'industry': 'ai_model', 'issuer': 'startup'},
                                            'autoFallback': False, 'autoFilled': []}}
        self.other = {'id': 'manus:other', 'title': '普通游戏新闻', 'url': 'https://example.org/other',
                      'publishedAt': '2026-09-22T09:00:00+08:00', 'summary': '',
                      'garenaSelection': {'status': 'not_selected', 'reason': '没有实质 AI 事件'}}

    def tearDown(self):
        snapshot.TAG_TAXONOMY = self.previous_taxonomy

    def test_raw_news_survives_and_selected_is_identical_except_index(self):
        chosen = {**self.selected, 'garenaSelection': {'status': 'selected', 'reason': '明确发布'}}
        prepared = {'items': [self.selected], 'allArticles': [chosen, self.other]}
        before = copy.deepcopy(prepared)
        result = snapshot.apply_article_pools({}, prepared, self.now)
        self.assertEqual(prepared, before)
        self.assertEqual(result['newsSelectionVersion'], 1)
        self.assertEqual([i['id'] for i in result['all']['items']], ['manus:other', 'aihot:chosen'])
        self.assertEqual(len(result['garenaSelected']['items']), 1)
        raw = result['all']['items'][0]
        self.assertEqual(raw['summary'], '')
        self.assertIsNone(raw['classification'])
        self.assertTrue(raw['categoryUnclassified'])
        all_item, selected_item = result['all']['items'][1], result['garenaSelected']['items'][0]
        self.assertEqual({k:v for k,v in all_item.items() if k != 'num'},
                         {k:v for k,v in selected_item.items() if k != 'num'})
        self.assertEqual((all_item['num'], selected_item['num']), (2, 1))

    def test_explicit_empty_selection_stays_empty(self):
        data = {'all': {'items': [self.selected]}, 'daily': {'sections': [{'items': [self.selected]}]}}
        result = snapshot.apply_article_pools(data, {'items': [], 'allArticles': [self.other]}, self.now)
        self.assertEqual(result['garenaSelected']['items'], [])
        self.assertEqual(len(result['all']['items']), 1)

    def test_library_must_contain_selected_and_agree_on_status(self):
        for library in ([self.other], [self.other, self.other], [self.selected]):
            with self.subTest(library=library), self.assertRaises(ValueError):
                snapshot.apply_article_pools({}, {'items': [self.selected], 'allArticles': library}, self.now)


if __name__ == '__main__':
    unittest.main()
