import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from manus_source.crawler import crawl_one
from manus_source.rendered_page import supported
sys.path.insert(0, str(Path(__file__).parent))
from _extraction_fake import fixture_extraction

_worker_patch = patch('manus_source.crawler._run_extraction', side_effect=fixture_extraction)

def setUpModule():
    _worker_patch.start()

def tearDownModule():
    _worker_patch.stop()


class RenderedArticleTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://jigou.jiqizhixin.com/articles/test'
        self.article = {'article_url': self.url, 'title': '测试模型发布',
                        'account_name': '机器之心', 'published_date': '2026-09-17'}
        self.promo = '<html><head><title>机器之心数据服务</title></head><body><p>数据服务</p></body></html>'.encode()
        self.good = ('<html><head><title>测试模型发布</title></head><body><article><p>' +
                     '这是已验证的公开文章正文，用于检验模型发布报道提取。' * 20 +
                     '</p></article></body></html>').encode()

    def test_promotional_response_is_replaced_by_rendered_article(self):
        render = Mock(return_value=(self.url, self.good))
        value = crawl_one(self.article, '2026-09-18',
                          transport=lambda u, h: (u, self.promo), render_fn=render)
        self.assertEqual(value['content_status'], 'complete')
        self.assertNotIn('数据服务', value['content_text'])
        render.assert_called_once()

    def test_rendered_redirect_never_enters_content(self):
        value = crawl_one(self.article, '2026-09-18',
            transport=lambda u, h: (u, self.promo),
            render_fn=Mock(return_value=('https://example.com/other', self.good)))
        self.assertEqual(value['content_status'], 'failed')
        self.assertEqual(value['content_text'], '')

    def test_failed_renderer_keeps_article_identity(self):
        value = crawl_one(self.article, '2026-09-18',
            transport=lambda u, h: (u, self.promo), render_fn=Mock(side_effect=TimeoutError))
        self.assertEqual(value['content_status'], 'failed')
        self.assertEqual(value['article_url'], self.url)

    def test_browser_scope_is_exact_https_article_host(self):
        self.assertTrue(supported(self.url))
        self.assertFalse(supported('https://jigou.jiqizhixin.com.evil.test/articles/test'))
        self.assertFalse(supported('http://jigou.jiqizhixin.com/articles/test'))
        self.assertFalse(supported('https://jigou.jiqizhixin.com/industry'))

    def test_discovery_body_is_reused_without_second_request(self):
        article = {**self.article, 'source_platform': 'Official Jiqizhixin',
                   'author': None, 'content_title': self.article['title'],
                   'content_text': '这是浏览器已经读取的文章正文。' * 50}
        with patch('manus_source.crawler.fetch_html') as request:
            result = crawl_one(article, '2026-09-18')
        request.assert_not_called()
        self.assertEqual(result['content_status'], 'complete')
        self.assertEqual(result['content_text'], article['content_text'])

    def test_mismatched_carried_title_is_not_used(self):
        article = {**self.article, 'source_platform': 'Official Jiqizhixin',
                   'content_title': '另一篇文章', 'content_text': '不应该接收的正文。' * 50}
        result = crawl_one(article, '2026-09-18', transport=lambda u,h: (u,self.promo))
        self.assertEqual(result['content_status'], 'failed')
