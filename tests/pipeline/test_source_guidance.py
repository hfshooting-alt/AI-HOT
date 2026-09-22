"""Source routes stay scoped and cannot invent access or tools."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from manus_source.source_guidance import render_source_guidance


class SourceGuidanceTests(unittest.TestCase):
    def test_single_tencent_source_does_not_receive_other_platform_instructions(self):
        text = render_source_guidance([{'platform': 'Tencent News', 'account_name': '测试账号'}])
        self.assertIn('om_article', text)
        self.assertIn('空壳', text)
        for unrelated in ('span.time', '/zh/elsewhere', '机器之心·数据服务'):
            self.assertNotIn(unrelated, text)

    def test_empty_or_unknown_source_set_does_not_invent_a_route(self):
        self.assertEqual(render_source_guidance([]), '')
        self.assertEqual(render_source_guidance([{'platform': 'Unverified platform'}]), '')

    def test_real_sources_are_unchanged_and_routes_are_deduplicated(self):
        config = json.loads((ROOT / 'config/manus_sources.json').read_text(encoding='utf-8'))
        sources = [row for rows in config['groups'].values() for row in rows]
        before = copy.deepcopy(sources)
        text = render_source_guidance(sources)
        self.assertEqual(sources, before)
        self.assertEqual(text.count('- Tencent News：'), 1)
        self.assertEqual(text.count('- NetEase：'), 1)
        self.assertEqual(text.count('- Official Elsewhere：'), 1)
        self.assertEqual(text.count('- Official Jiqizhixin：'), 1)
        self.assertNotIn('browser.navigate', text)
        self.assertNotIn('getSubNewsMixedList', text)

    def test_netease_pairs_same_article_link_and_time(self):
        text = render_source_guidance([{'platform': 'NetEase'}])
        self.assertIn('同一个 li.js-item.item', text)
        self.assertIn('h4 a.title', text)
        self.assertIn('span.time', text)
        self.assertIn('相邻文章时间', text)

    def test_elsewhere_requires_visible_matching_author_and_original_publication_time(self):
        text = render_source_guidance([{'platform': 'Official Elsewhere'}])
        self.assertIn('多创作者混合列表', text)
        self.assertIn('当前可见的匹配链接', text)
        self.assertIn('article:author', text)
        self.assertIn('datePublished', text)
        self.assertIn('不能取 dateModified', text)

    def test_jiqizhixin_service_page_is_failure_without_bypassing_or_replacing_source(self):
        text = render_source_guidance([{'platform': 'Official Jiqizhixin'}])
        self.assertIn('source_status=failed、note=list_blocked', text)
        self.assertIn('用户选择', text)
        self.assertIn('不绕过限制', text)
        self.assertIn('作者缺失可为 null', text)


if __name__ == '__main__':
    unittest.main()
