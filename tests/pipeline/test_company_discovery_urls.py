import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from company_index.discovery import discover, reserve, urls_from


class CompanyDiscoveryUrlsTest(unittest.TestCase):
    URLS = [
        'https://www.tripo3d.ai/research',
        'https://www.tripo3d.ai/blog/sony-and-vast-3d-business-collabration',
        'https://www.scmp.com/tech/tech-trends/article/3338202/china-founded-tripo-ai-updates-3d-content-creation-platform-users-more-double',
        'https://github.com/VAST-AI-Research',
    ]

    def test_actual_vast_checkpoint_splits_only_explicit_links(self):
        joined = '、'.join('`' + url + '`' for url in self.URLS) + '。'
        inputs = [
            '已发现以下有用来源，先记录为文本检查点，再继续核验：' + joined,
            {'evidence': [{'url': joined}]},
            {'urls': [joined, self.URLS[1]]},
            [joined],
        ]
        for value in inputs:
            with self.subTest(value=value):
                self.assertEqual(urls_from(value), self.URLS)

    def test_markdown_and_query_survive_without_widening_scheme_policy(self):
        value = ('[Legal](https://example.com/legal?lang=zh&source=about) '
                 '<https://example.com/legal?lang=zh&source=about> '
                 'http://example.org http://localhost https://user:pass@example.com/ '
                 'mailto:team@example.org example.net/about https://[broken')
        self.assertEqual(urls_from(value), ['https://example.com/legal?lang=zh&source=about'])

    def test_discovery_still_returns_at_most_three_and_preserves_checkpoint(self):
        client = Mock()
        client.available_credits.return_value = 100
        client.create_crawl_task.return_value = SimpleNamespace(task_id='offline', task_url='https://example.com/task')
        client.wait_for_structured_result.return_value = {'evidence': [{'url': '、'.join('`'+u+'`' for u in self.URLS)}]}
        client._request.return_value = {'task': {'credit_usage': 3, 'status': 'stopped'}}
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'COMPANY_DISCOVERY_QUOTA_READY': '1'}):
            reserve(folder, '2026-09-20')
            result = discover({'id': 'company:vast', 'company_name': 'VAST'}, directory=folder, client=client, day='2026-09-20')
            saved = json.loads((Path(folder) / '2026-09-20-links.json').read_text(encoding='utf8'))
        self.assertEqual(result['urls'], self.URLS[:3])
        self.assertEqual(saved['urls'], self.URLS)
        client.create_crawl_task.assert_called_once()
