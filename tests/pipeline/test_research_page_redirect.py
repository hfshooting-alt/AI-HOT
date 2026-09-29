import unittest
from unittest.mock import patch

from company_index.page_evidence import read_page


class ResearchPageRedirectTest(unittest.TestCase):
    mobile = 'https://view.inews.qq.com/a/20260923A06QC800'
    desktop = 'https://news.qq.com/rain/a/20260923A06QC800?id=20260923A06QC800&redirect_pc=1'

    def read(self, original, final, risk=False):
        with patch('company_index.page_evidence.fetch_html', return_value=(final, b'<html></html>')), \
             patch('company_index.page_evidence.extract_text', return_value=('Verified article body. ' * 20, 'Title')), \
             patch('company_index.page_evidence._looks_like_risk_page', return_value=risk):
            return read_page(original)

    def test_exact_observed_tencent_alias_keeps_original_evidence_url(self):
        self.assertEqual(self.read(self.mobile, self.desktop)['url'], self.mobile)

    def test_other_article_or_unverified_alias_is_rejected(self):
        for final in [self.desktop.replace('A06QC800', 'A06XL900'),
                      self.desktop.replace('news.qq.com', 'news.qq.com.evil.example'),
                      self.desktop.replace('https:', 'http:'),
                      self.desktop + '&id=20260923A06XL900',
                      'https://news.qq.com/',
                      self.mobile.replace('A06QC800', 'A06XL900')]:
            with self.subTest(final=final), self.assertRaises(ValueError):
                self.read(self.mobile, final)

    def test_unrelated_cross_host_stays_rejected(self):
        with self.assertRaises(ValueError):
            self.read('https://company.example/about', 'https://other.example/about')
        self.assertEqual(self.read('https://company.example/about', 'https://company.example/company')['url'],
                         'https://company.example/about')

    def test_alias_does_not_bypass_risk_page_guard(self):
        with self.assertRaisesRegex(ValueError, '页面正文不足'):
            self.read(self.mobile, self.desktop, risk=True)


if __name__ == '__main__':
    unittest.main()
