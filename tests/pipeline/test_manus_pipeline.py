#!/usr/bin/env python3
"""test_manus_pipeline.py — 阶段 B 正文采集编排离线单测（不发真实 Manus 请求）。

运行：python -m unittest tests.test_manus_pipeline -v
"""
import json
import os
import re
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
from _tempdir import make_temp_dir  # noqa: E402
from manus_source import contracts  # noqa: E402
from manus_source.pipeline import ContentPipeline, ScriptContentProvider, plan_batches  # noqa: E402
from manus_source.crawler import DEFAULT_USER_AGENT  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "manus")
CRAWLER_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "crawler")
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "manus_content.md")
TARGET_DATE = "2026-08-16"


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def all_discoveries() -> dict:
    return {
        "group_a": load_fixture("discovery-group-a.json"),
        "group_b": load_fixture("discovery-group-b.json"),
        "group_c": load_fixture("discovery-group-c.json"),
    }


class FakeContentClient:
    """按请求清单（从 task brief 解析 URL）从正文夹具中回填结果。"""

    def __init__(self, fixture: dict, target_date: str):
        self.by_url = {a["article_url"]: a for a in fixture["articles"]}
        self.target_date = target_date
        self.created = []
        self._pending_urls: list[str] = []

    def create_crawl_task(self, prompt_text, source_group, target_date, title, task_brief,
                          output_schema=None):
        urls = re.findall(r"article_url：(\S+)", task_brief)
        self.created.append(urls)
        self._pending_urls = urls

        class _Task:
            task_id = f"fake-{len(self.created)}"
            task_url = f"https://manus.app/task/fake-{len(self.created)}"
        return _Task()

    def wait_for_structured_result(self, task_id):
        articles = [dict(self.by_url[u]) for u in self._pending_urls if u in self.by_url]
        return {"target_date": self.target_date, "articles": articles}


class AssertNotCalledClient:
    def create_crawl_task(self, **kw):
        raise AssertionError("断点续跑不应再创建 Manus 任务")

    def wait_for_structured_result(self, task_id):
        raise AssertionError("断点续跑不应再轮询 Manus 任务")


class TestPlanBatches(unittest.TestCase):
    def test_dedup_and_chunking(self):
        batches, dropped = plan_batches(all_discoveries(), batch_size=4)
        self.assertEqual(dropped, 1)  # ZPotential 与 FounderPark 同 URL
        urls = [a["article_url"] for b in batches for a in b]
        self.assertEqual(len(urls), 11)
        self.assertEqual(len(set(urls)), 11)
        self.assertEqual([len(b) for b in batches], [4, 4, 3])


class TestContentPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir("manus-pipeline-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.prompt_text = open(PROMPT_PATH, encoding="utf-8").read()

    def make_pipeline(self, client):
        return ContentPipeline(client, self.prompt_text, TARGET_DATE, self.tmp,
                               batch_size=4, max_content_chars=20000, min_content_chars=100)

    def test_full_run_end_to_end(self):
        client = FakeContentClient(load_fixture("content-batch.json"), TARGET_DATE)
        result = self.make_pipeline(client).run(all_discoveries())
        self.assertEqual(result.duplicates_dropped, 1)
        self.assertEqual(result.batches_run, 3)
        self.assertEqual(result.batches_resumed, 0)
        self.assertEqual(len(result.ok_articles), 9)
        self.assertEqual(len(result.failed), 2)
        reasons = {f["article_url"]: f["reason"] for f in result.failed}
        self.assertIn("风控", reasons["https://news.qq.com/rain/a/20260816A01GEEK000"])
        self.assertIn("不一致", reasons["https://news.qq.com/rain/a/20260816A01VC00000"])
        # ok 文章均带合法正文
        for art in result.ok_articles:
            self.assertGreaterEqual(len(art["content_text"]), 100)
        # 原始与诊断文件都已落盘
        raw_dir = os.path.join(self.tmp, TARGET_DATE, "raw")
        diag_dir = os.path.join(self.tmp, "diagnostics", TARGET_DATE)
        self.assertEqual(sorted(os.listdir(raw_dir))[:3],
                         ["content-batch-01.json", "content-batch-02.json", "content-batch-03.json"])
        diag_text = open(os.path.join(diag_dir, "content-batch-01.json"), encoding="utf-8").read()
        self.assertNotIn("content_text", diag_text)  # 诊断不含正文
        summary = json.load(open(os.path.join(diag_dir, "summary.json"), encoding="utf-8"))
        self.assertEqual(summary["ok_count"], 9)

    def test_full_resume_avoids_all_manus_calls(self):
        fixture = load_fixture("content-batch.json")
        self.make_pipeline(FakeContentClient(fixture, TARGET_DATE)).run(all_discoveries())
        result = self.make_pipeline(AssertNotCalledClient()).run(all_discoveries())
        self.assertEqual(result.batches_resumed, 3)
        self.assertEqual(result.batches_run, 0)
        self.assertEqual(len(result.ok_articles), 9)

    def test_partial_resume_only_reruns_missing_batch(self):
        fixture = load_fixture("content-batch.json")
        self.make_pipeline(FakeContentClient(fixture, TARGET_DATE)).run(all_discoveries())
        os.remove(os.path.join(self.tmp, TARGET_DATE, "raw", "content-batch-02.json"))
        client = FakeContentClient(fixture, TARGET_DATE)
        result = self.make_pipeline(client).run(all_discoveries())
        self.assertEqual(result.batches_resumed, 2)
        self.assertEqual(result.batches_run, 1)
        self.assertEqual(len(result.ok_articles), 9)

    def test_corrupted_batch_file_is_ignored(self):
        fixture = load_fixture("content-batch.json")
        self.make_pipeline(FakeContentClient(fixture, TARGET_DATE)).run(all_discoveries())
        bad_path = os.path.join(self.tmp, TARGET_DATE, "raw", "content-batch-99.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{这不是合法 JSON")
        result = self.make_pipeline(AssertNotCalledClient()).run(all_discoveries())
        self.assertEqual(result.batches_resumed, 3)  # 损坏文件不影响合法批次复用

    def test_batch_result_url_mismatch_raises(self):
        class DroppingClient(FakeContentClient):
            def wait_for_structured_result(self, task_id):
                payload = super().wait_for_structured_result(task_id)
                payload["articles"] = payload["articles"][:-1]  # 故意漏一篇
                return payload

        client = DroppingClient(load_fixture("content-batch.json"), TARGET_DATE)
        with self.assertRaises(contracts.ContractError):
            self.make_pipeline(client).run(all_discoveries())

    def test_prompt_renders_max_chars(self):
        pipeline = self.make_pipeline(AssertNotCalledClient())
        self.assertIn("20000", pipeline.prompt_text)
        self.assertNotIn("{{MAX_CONTENT_CHARS}}", pipeline.prompt_text)


class TestScriptContentPipeline(unittest.TestCase):
    """脚本爬虫模式端到端：ScriptContentProvider + 注入 fake transport，不发真实请求。"""

    def setUp(self):
        self.tmp = make_temp_dir("manus-script-pipeline-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.prompt_text = open(PROMPT_PATH, encoding="utf-8").read()
        base_html = open(os.path.join(CRAWLER_FIXTURE_DIR, "tencent_article.html"),
                         encoding="utf-8").read()
        old_title = "单人3个月做的AI游戏，Steam好评率94%：「我曾对游戏开发一无所知」"
        titles = {a["article_url"]: a["title"]
                  for payload in all_discoveries().values()
                  for a in payload["articles"] if a.get("article_url")}
        # 每条 URL 都返回同一份腾讯 fixture 正文，但标题回填为发现记录对应标题
        self.transport = lambda url, headers: (
            url, base_html.replace(old_title, titles.get(url, old_title)).encode("utf-8"))

    def make_provider(self, **kw):
        kw.setdefault("concurrency", 2)
        kw.setdefault("timeout_seconds", 5)
        kw.setdefault("retries", 0)
        kw.setdefault("request_delay_seconds", 0)
        return ScriptContentProvider(TARGET_DATE, transport=self.transport, **kw)

    def test_full_run_via_script_provider(self):
        pipeline = ContentPipeline(self.make_provider(), self.prompt_text, TARGET_DATE,
                                   self.tmp, batch_size=4, max_content_chars=20000,
                                   min_content_chars=100)
        result = pipeline.run(all_discoveries())
        self.assertEqual(result.duplicates_dropped, 1)
        self.assertEqual(result.batches_run, 3)
        self.assertEqual(result.batches_resumed, 0)
        # 脚本模式全成功：去重后 11 条全部通过（Manus 夹具里的 2 篇失败场景不适用）
        self.assertEqual(len(result.ok_articles), 11)
        self.assertEqual(result.failed, [])
        # 契约通过且原始批次落盘
        raw_dir = os.path.join(self.tmp, TARGET_DATE, "raw")
        self.assertEqual(len(glob_content_batches(raw_dir)), 3)

    def test_script_provider_resume_reuses_raw_batches(self):
        pipeline = ContentPipeline(self.make_provider(), self.prompt_text, TARGET_DATE,
                                   self.tmp, batch_size=4, max_content_chars=20000,
                                   min_content_chars=100)
        pipeline.run(all_discoveries())

        def fail_transport(url, headers):
            raise AssertionError("断点续跑不应再发起爬取请求")

        provider = ScriptContentProvider(TARGET_DATE, transport=fail_transport)
        result = ContentPipeline(provider, self.prompt_text, TARGET_DATE,
                                 self.tmp, batch_size=4, max_content_chars=20000,
                                 min_content_chars=100).run(all_discoveries())
        self.assertEqual(result.batches_resumed, 3)
        self.assertEqual(result.batches_run, 0)
        self.assertEqual(len(result.ok_articles), 11)

    def test_short_text_fails_via_contract(self):
        # 风控页 fixture 提取文本短 → 爬虫层 failed，不进入 ok
        risk_html = open(os.path.join(CRAWLER_FIXTURE_DIR, "risk_page.html"),
                         encoding="utf-8").read()
        self.transport = lambda url, headers: (url, risk_html.encode("utf-8"))
        pipeline = ContentPipeline(self.make_provider(), self.prompt_text, TARGET_DATE,
                                   self.tmp, batch_size=4, max_content_chars=20000,
                                   min_content_chars=100)
        result = pipeline.run(all_discoveries())
        self.assertEqual(result.ok_articles, [])
        self.assertGreaterEqual(len(result.failed), 1)
        self.assertTrue(any("风控" in f["reason"] for f in result.failed))


def glob_content_batches(raw_dir: str) -> list:
    return sorted(p for p in os.listdir(raw_dir) if p.startswith("content-batch-"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
