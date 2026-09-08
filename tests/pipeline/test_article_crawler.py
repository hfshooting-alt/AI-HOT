#!/usr/bin/env python3
"""test_article_crawler.py — 阶段 B 本地脚本爬虫离线单测（不发真实网络请求）。

覆盖：抓取/重试、跳转漂移、trafilatura 提取、风控页、正文过短、标题一致性、
超长截断、jina 回退、批量顺序。运行：python -m unittest tests.test_article_crawler -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from manus_source import crawler  # noqa: E402
from manus_source import contracts  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "crawler")
TARGET_DATE = "2026-08-19"

TENCENT_URL = "https://news.qq.com/rain/a/20260819A0B8ML00"
TENCENT_TITLE = "单人3个月做的AI游戏，Steam好评率94%：「我曾对游戏开发一无所知」"
NETEASE_URL = "https://www.163.com/dy/article/L4MQ04250556EX0D.html?spss=dy_author"
NETEASE_TITLE = "Z Fund｜专访敦鸿资产合伙人俞文超：5年前10亿估值押注宇树，所有人都在问「机器狗能干什么」"


def load_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURE_DIR, name), "rb") as f:
        return f.read()


def make_article(url=TENCENT_URL, title=TENCENT_TITLE):
    return {"account_name": "游戏葡萄", "article_url": url, "title": title,
            "published_date": TARGET_DATE}


def make_transport(url_map):
    """按 URL 返回 (final_url, html_bytes)；未命中抛 OSError 模拟网络失败。"""
    def transport(url, headers):
        if url not in url_map:
            raise OSError(f"connection reset for {url}")
        final_url, data = url_map[url]
        return final_url, data
    return transport


class TestFetchHtml(unittest.TestCase):
    def test_success_and_final_url(self):
        t = make_transport({TENCENT_URL: (TENCENT_URL, load_fixture("tencent_article.html"))})
        final, data = crawler.fetch_html(TENCENT_URL, transport=t)
        self.assertEqual(final, TENCENT_URL)
        self.assertGreater(len(data), 0)

    def test_retries_then_success(self):
        calls = {"n": 0}

        def flaky(url, headers):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("transient")
            return TENCENT_URL, load_fixture("tencent_article.html")

        final, data = crawler.fetch_html(TENCENT_URL, retries=3, retry_base_seconds=0,
                                         transport=flaky)
        self.assertEqual(calls["n"], 3)

    def test_retries_exhausted_raises(self):
        def always_fail(url, headers):
            raise OSError("down")

        with self.assertRaises(crawler.CrawlError):
            crawler.fetch_html(TENCENT_URL, retries=1, retry_base_seconds=0,
                               transport=always_fail)


class TestUrlDrift(unittest.TestCase):
    def test_same_url_no_drift(self):
        self.assertFalse(crawler._url_drifted(TENCENT_URL, TENCENT_URL))

    def test_query_change_ignored(self):
        self.assertFalse(crawler._url_drifted(
            "https://www.163.com/dy/article/L4MQ04250556EX0D.html?spss=dy_author",
            "https://www.163.com/dy/article/L4MQ04250556EX0D.html"))

    def test_host_change_is_drift(self):
        self.assertTrue(crawler._url_drifted(TENCENT_URL, "https://other.example/x"))

    def test_path_change_is_drift(self):
        self.assertTrue(crawler._url_drifted(TENCENT_URL, "https://news.qq.com/rain/a/OTHER00"))


class TestTitleMismatch(unittest.TestCase):
    def test_exact_match(self):
        self.assertFalse(crawler._title_mismatch(TENCENT_TITLE, TENCENT_TITLE))

    def test_whitespace_drift_tolerated(self):
        # 冒烟报告问题 3：Manus 抄写标题多一个空格 —— 子串包含容忍
        with_space = "单人3个月做的AI游戏， Steam好评率94%：「我曾对游戏开发一无所知」"
        self.assertFalse(crawler._title_mismatch(TENCENT_TITLE, with_space))

    def test_site_suffix_tolerated(self):
        self.assertFalse(crawler._title_mismatch(TENCENT_TITLE, TENCENT_TITLE + "_腾讯新闻"))

    def test_totally_different_is_mismatch(self):
        self.assertTrue(crawler._title_mismatch(TENCENT_TITLE, "另一篇完全不同的文章标题"))

    def test_empty_side_is_not_mismatch(self):
        self.assertFalse(crawler._title_mismatch(TENCENT_TITLE, ""))


class TestTruncate(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(crawler.truncate_head_tail("短", 100), "短")

    def test_long_text_within_limit(self):
        text = "字" * 5000
        out = crawler.truncate_head_tail(text, 1000)
        self.assertLessEqual(len(out), 1000)
        self.assertIn("截断", out)
        self.assertTrue(out.startswith("字" * 10))
        self.assertTrue(out.endswith("字" * 10))


class TestCrawlOne(unittest.TestCase):
    def setUp(self):
        self.t = make_transport({TENCENT_URL: (TENCENT_URL, load_fixture("tencent_article.html")),
                                 NETEASE_URL: (NETEASE_URL, load_fixture("netease_article.html")),
                                 "https://news.qq.com/rain/a/RISK00": ("https://news.qq.com/rain/a/RISK00",
                                                                        load_fixture("risk_page.html")),
                                 "https://news.qq.com/rain/a/GONE00": ("https://news.qq.com/rain/a/GONE00",
                                                                        load_fixture("no_content.html")),
                                 "https://news.qq.com/rain/a/DRIFT00": ("https://news.qq.com/rain/a/DRIFT00",
                                                                         load_fixture("drift_page.html"))})
        self.kw = {"timeout_seconds": 5, "retries": 0, "request_delay_seconds": 0,
                   "transport": self.t}

    def test_tencent_complete(self):
        rec = crawler.crawl_one(make_article(), TARGET_DATE, **self.kw)
        self.assertEqual(rec["content_status"], "complete")
        self.assertIn("群侠传", rec["content_text"])
        self.assertFalse(rec["content_truncated"])
        self.assertIsNone(rec["note"])

    def test_netease_complete(self):
        rec = crawler.crawl_one(make_article(NETEASE_URL, NETEASE_TITLE), TARGET_DATE, **self.kw)
        self.assertEqual(rec["content_status"], "complete")
        self.assertIn("宇树科技", rec["content_text"])

    def test_risk_page_failed(self):
        rec = crawler.crawl_one(make_article("https://news.qq.com/rain/a/RISK00"), TARGET_DATE,
                                **self.kw)
        self.assertEqual(rec["content_status"], "failed")
        self.assertIn("风控", rec["note"])

    def test_short_page_failed(self):
        rec = crawler.crawl_one(make_article("https://news.qq.com/rain/a/GONE00"), TARGET_DATE,
                                **self.kw)
        self.assertEqual(rec["content_status"], "failed")
        self.assertIn("正文过短", rec["note"])

    def test_title_drift_failed(self):
        rec = crawler.crawl_one(make_article("https://news.qq.com/rain/a/DRIFT00"), TARGET_DATE,
                                **self.kw)
        self.assertEqual(rec["content_status"], "failed")
        self.assertIn("跳转漂移", rec["note"])

    def test_redirect_drift_failed(self):
        t = make_transport({TENCENT_URL: ("https://news.qq.com/rain/a/OTHER00",
                                          load_fixture("tencent_article.html"))})
        rec = crawler.crawl_one(make_article(), TARGET_DATE, transport=t, retries=0)
        self.assertEqual(rec["content_status"], "failed")
        self.assertIn("跳转漂移", rec["note"])

    def test_fetch_failure_failed(self):
        t = make_transport({})  # 所有 URL 抛网络异常
        rec = crawler.crawl_one(make_article(), TARGET_DATE, transport=t, retries=0)
        self.assertEqual(rec["content_status"], "failed")
        self.assertIn("抓取失败", rec["note"])

    def test_truncation_when_over_limit(self):
        rec = crawler.crawl_one(make_article(), TARGET_DATE, max_content_chars=120,
                                min_content_chars=100, **self.kw)
        self.assertEqual(rec["content_status"], "complete")
        self.assertTrue(rec["content_truncated"])
        self.assertLessEqual(len(rec["content_text"]), 120)
        self.assertIn("截断", rec["note"])

    def test_jina_fallback_used_when_extract_fails(self):
        with mock.patch.object(crawler, "extract_text", return_value=(None, None)), \
             mock.patch.object(crawler, "fetch_jina_text", return_value="回退正文内容，" + "够长。" * 50):
            rec = crawler.crawl_one(make_article(), TARGET_DATE, jina_fallback=True, **self.kw)
        self.assertEqual(rec["content_status"], "complete")
        self.assertIn("回退正文内容", rec["content_text"])

    def test_jina_fallback_disabled(self):
        with mock.patch.object(crawler, "extract_text", return_value=(None, None)), \
             mock.patch.object(crawler, "fetch_jina_text", return_value="不应被调用") as jina:
            rec = crawler.crawl_one(make_article(), TARGET_DATE, jina_fallback=False, **self.kw)
        jina.assert_not_called()
        self.assertEqual(rec["content_status"], "failed")


class TestCrawlBatch(unittest.TestCase):
    def test_order_and_urls_match_request(self):
        t = make_transport({TENCENT_URL: (TENCENT_URL, load_fixture("tencent_article.html")),
                            NETEASE_URL: (NETEASE_URL, load_fixture("netease_article.html"))})
        batch = [make_article(), make_article(NETEASE_URL, NETEASE_TITLE)]
        payload = crawler.crawl_batch(batch, TARGET_DATE, concurrency=2,
                                      timeout_seconds=5, retries=0, transport=t)
        self.assertEqual(payload["target_date"], TARGET_DATE)
        self.assertEqual([a["article_url"] for a in payload["articles"]],
                         [TENCENT_URL, NETEASE_URL])
        self.assertTrue(all(a["content_status"] == "complete" for a in payload["articles"]))

    def test_batch_result_passes_contract(self):
        t = make_transport({TENCENT_URL: (TENCENT_URL, load_fixture("tencent_article.html")),
                            NETEASE_URL: (NETEASE_URL, load_fixture("netease_article.html"))})
        batch = [make_article(), make_article(NETEASE_URL, NETEASE_TITLE)]
        payload = crawler.crawl_batch(batch, TARGET_DATE, concurrency=2,
                                      timeout_seconds=5, retries=0, transport=t)
        expected_titles = {a["article_url"]: a["title"] for a in batch}
        ok, failed = contracts.validate_content_batch(payload, TARGET_DATE, expected_titles)
        self.assertEqual(len(ok), 2)
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
