"""Offline regressions for observed Tencent redirects and preserved body gates."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from manus_source import crawler
from manus_source.source_urls import same_tencent_article, tencent_article_id


ARTICLE_IDS = ('20260921A07K2K00', '20260921A07K2300')


class TencentArticleUrls(unittest.TestCase):
    def test_observed_mobile_to_desktop_redirects_keep_original_url(self):
        for ident in ARTICLE_IDS:
            with self.subTest(ident=ident):
                mobile = 'https://view.inews.qq.com/a/' + ident
                desktop = 'https://news.qq.com/rain/a/' + ident + '?id=' + ident + '&path=a&redirect_pc=1'
                self.assertEqual(tencent_article_id(mobile), ident)
                self.assertEqual(tencent_article_id(desktop), ident)
                self.assertTrue(same_tencent_article(mobile, desktop))
                self.assertFalse(crawler._url_drifted(mobile, desktop))
                article = {'account_name': '新智元', 'article_url': mobile,
                           'title': '已核实文章标题', 'published_date': '2026-09-21'}
                with patch.object(crawler, 'extract_text', return_value=('正文内容' * 40, article['title'])):
                    result = crawler.crawl_one(article, '2026-09-22', retries=0,
                        transport=lambda url, headers: (desktop, b'<html><head></head></html>'))
                self.assertEqual(result['content_status'], 'complete')
                self.assertEqual(result['article_url'], mobile)

    def test_different_articles_never_match(self):
        left = 'https://view.inews.qq.com/a/' + ARTICLE_IDS[0]
        right = 'https://news.qq.com/rain/a/' + ARTICLE_IDS[1]
        self.assertFalse(same_tencent_article(left, right))
        self.assertTrue(crawler._url_drifted(left, right))

    def test_ambiguous_or_untrusted_aliases_rejected(self):
        ident, other = ARTICLE_IDS
        valid = 'https://news.qq.com/rain/a/' + ident
        invalid = [
            'http://news.qq.com/rain/a/' + ident,
            'ftp://news.qq.com/rain/a/' + ident,
            '//news.qq.com/rain/a/' + ident,
            'https://user@news.qq.com/rain/a/' + ident,
            'https://user:pass@news.qq.com/rain/a/' + ident,
            'https://news.qq.com:443/rain/a/' + ident,
            'https://news.qq.com:/rain/a/' + ident,
            'https://news.qq.com.evil.example/rain/a/' + ident,
            'https://evil.example/rain/a/' + ident,
            'https://news.qq.com./rain/a/' + ident,
            'https://news.qq.com/rain/a/%32' + ident[1:],
            'https://news.qq.com/rain%2fa/' + ident,
            'https://news.qq.com/rain/a/' + ident + '/',
            'https://news.qq.com/rain/a/' + ident + '/extra',
            'https://view.inews.qq.com/rain/a/' + ident,
            valid + '?id=' + other,
            valid + '?id=',
            valid + '?id=' + ident + '&id=' + other,
            valid + '?%69d=' + other,
            valid + '?ID=' + other,
            valid + '\n',
            valid.replace('news.', 'ne\tws.'),
            valid.replace('/rain', '\\rain'),
        ]
        for url in invalid:
            with self.subTest(url=url):
                self.assertIsNone(tencent_article_id(url))
                self.assertFalse(same_tencent_article(valid, url))
                self.assertTrue(crawler._url_drifted(valid, url))

    def test_same_id_tracking_and_fragment_variants(self):
        ident = ARTICLE_IDS[0]
        left = 'https://view.inews.qq.com/a/' + ident
        right = 'https://NEWS.QQ.COM/a/' + ident + '?id=' + ident + '&from=app#comments'
        self.assertTrue(same_tencent_article(left, right))
        self.assertFalse(crawler._url_drifted(left, right))

    def test_same_id_redirect_retains_title_length_and_risk_gates(self):
        ident = ARTICLE_IDS[0]
        mobile = 'https://view.inews.qq.com/a/' + ident
        desktop = 'https://news.qq.com/rain/a/' + ident
        article = {'account_name': '新智元', 'article_url': mobile,
                   'title': '已核实文章标题', 'published_date': '2026-09-21'}
        cases = [('正文内容' * 40, '完全不同的文章', b'<html></html>', '标题'),
                 ('太短', article['title'], b'<html></html>', '正文过短'),
                 ('正文内容' * 40, article['title'], '<head><title>验证码</title></head>'.encode(), '风控')]
        for text, title, html, reason in cases:
            with self.subTest(reason=reason), patch.object(crawler, 'extract_text', return_value=(text, title)):
                result = crawler.crawl_one(article, '2026-09-22', retries=0,
                    transport=lambda url, headers: (desktop, html))
                self.assertEqual(result['content_status'], 'failed')
                self.assertIn(reason, result['note'])

    def test_other_platform_query_compatibility_unchanged(self):
        self.assertFalse(crawler._url_drifted('https://www.163.com/dy/article/A.html?from=x',
                                             'https://www.163.com/dy/article/A.html'))
        self.assertTrue(crawler._url_drifted('https://www.163.com/dy/article/A.html',
                                            'https://www.163.com/dy/article/B.html'))


if __name__ == '__main__':
    unittest.main()
