import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from manus_source.crawler import crawl_one
from manus_source.rendered_page import supported


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
