#!/usr/bin/env python3
"""test_build_manus_feed.py — Manus 规范化 feed 构建离线端到端测试。

从 fixtures 模拟 work 目录原始产物 → 构建 → 校验 → 原子晋升；不发 Manus/模型请求。

运行：python -m unittest tests.test_build_manus_feed -v
"""
import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
from _tempdir import make_temp_dir  # noqa: E402
import build_manus_feed  # noqa: E402
import enrich_news  # noqa: E402
from manus_source import contracts  # noqa: E402

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "manus")
SOURCES_PATH = os.path.join(PROJECT_ROOT, "config/manus_sources.json")
TAXONOMY_PATH = os.path.join(PROJECT_ROOT, "config/taxonomy.json")
TARGET_DATE = "2026-08-16"
FIXED_GENERATED_AT = "2026-08-17T03:40:00+08:00"


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def fake_enricher(items, tx, cache_path):
    """确定性加工器：首段截断摘要 + general 分类；赛博禅心走 fallback 分支。"""
    results = {}
    for it in items:
        key = enrich_news.enrich_item_key(it)
        first_para = (it["content_text"].split("\n")[0])[:200]
        if it["mpName"] == "赛博禅心":
            results[key] = {"summary": first_para,
                            "classification": {"category": "general", "tags": {},
                                               "autoFallback": True, "autoFilled": []},
                            "enrichmentStatus": "fallback"}
        else:
            results[key] = {"summary": first_para + "。以上为模型生成的事实摘要。" * 3,
                            "classification": {"category": "general", "tags": {},
                                               "autoFallback": False, "autoFilled": []},
                            "enrichmentStatus": "complete"}
    return results


class TestBuildManusFeed(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir("manus-feed-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.work_dir = os.path.join(self.tmp, "work", "manus")
        self.data_dir = os.path.join(self.tmp, "data", "manus")
        raw_dir = os.path.join(self.work_dir, TARGET_DATE, "raw")
        os.makedirs(raw_dir)
        for group in ("a", "b", "c"):
            shutil.copy(os.path.join(FIXTURE_DIR, f"discovery-group-{group}.json"),
                        os.path.join(raw_dir, f"discovery-group_{group}.json"))
        shutil.copy(os.path.join(FIXTURE_DIR, "content-batch.json"),
                    os.path.join(raw_dir, "content-batch-01.json"))

    def do_build(self):
        return build_manus_feed.build(TARGET_DATE, self.work_dir, SOURCES_PATH, TAXONOMY_PATH,
                                      enrich_fn=fake_enricher, generated_at=FIXED_GENERATED_AT)

    def test_e2e_build_and_promote(self):
        feed = self.do_build()
        contracts.validate_feed(feed, TAXONOMY_PATH)
        path = build_manus_feed.promote_feed(feed, self.data_dir, TAXONOMY_PATH)
        self.assertTrue(os.path.exists(path))
        # 12 发现 − 1 重复 − 2 正文失败 = 9 发布；ZFinance 来源失败 → degraded
        self.assertEqual(feed["stats"]["discoveredArticles"], 12)
        self.assertEqual(feed["stats"]["publishedArticles"], 9)
        self.assertEqual(feed["stats"]["fallbackArticles"], 1)
        self.assertTrue(feed["ok"] and feed["degraded"])
        # 按日归档副本同步落盘
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "archive",
                                                    f"{TARGET_DATE}.json")))
        # 正文失败的文章不在发布数据中
        urls = {it["url"] for it in feed["items"]}
        self.assertNotIn("https://news.qq.com/rain/a/20260816A01GEEK000", urls)
        self.assertNotIn("https://news.qq.com/rain/a/20260816A01VC00000", urls)

    def test_state_written_on_success(self):
        feed = self.do_build()
        build_manus_feed.promote_feed(feed, self.data_dir, TAXONOMY_PATH)
        build_manus_feed.write_state(os.path.join(self.data_dir, "state.json"),
                                     TARGET_DATE, True, feed, None)
        state = json.load(open(os.path.join(self.data_dir, "state.json"), encoding="utf-8"))
        self.assertTrue(state["promoted"])
        self.assertEqual(state["lastSuccessDate"], TARGET_DATE)
        self.assertIsNone(state["failure"])

    def test_repeated_build_is_byte_identical(self):
        feed1 = self.do_build()
        feed2 = self.do_build()
        self.assertEqual(json.dumps(feed1, ensure_ascii=False, sort_keys=True),
                         json.dumps(feed2, ensure_ascii=False, sort_keys=True))

    def test_stable_ids_and_enrichment_preserved(self):
        feed = self.do_build()
        for it in feed["items"]:
            account = it["mpName"]
            want_id = contracts.stable_article_id(account, TARGET_DATE, it["title"])
            self.assertEqual(it["id"], want_id)
            self.assertTrue(it["summary"])  # 摘要来自加工器，未被覆盖
        fallback = [it for it in feed["items"] if it["enrichmentStatus"] == "fallback"]
        self.assertEqual([it["mpName"] for it in fallback], ["赛博禅心"])
        self.assertTrue(fallback[0]["classification"]["autoFallback"])

    def test_source_identity_uses_actual_carrier(self):
        feed = self.do_build()
        self.assertEqual(feed["schemaVersion"], 2)
        by_platform = {it["sourcePlatform"]: it for it in feed["items"]}
        self.assertEqual(by_platform["Tencent News"]["sourceType"], "media")
        self.assertEqual(by_platform["Tencent News"]["sourceChannel"], "tencent_syndication")
        self.assertTrue(by_platform["Tencent News"]["source"].startswith("腾讯新闻转载："))

    def test_missing_group_raises_and_old_feed_survives(self):
        feed = self.do_build()
        build_manus_feed.promote_feed(feed, self.data_dir, TAXONOMY_PATH)
        before = open(os.path.join(self.data_dir, "current.json"), encoding="utf-8").read()
        os.remove(os.path.join(self.work_dir, TARGET_DATE, "raw", "discovery-group_b.json"))
        with self.assertRaises(contracts.ContractError):
            self.do_build()
        # 失败不得覆盖上一次成功 feed
        after = open(os.path.join(self.data_dir, "current.json"), encoding="utf-8").read()
        self.assertEqual(before, after)
        # 失败状态可记录且不影响 lastSuccessDate
        build_manus_feed.write_state(os.path.join(self.data_dir, "state.json"),
                                     TARGET_DATE, False, None, "缺少发现结果文件")
        state = json.load(open(os.path.join(self.data_dir, "state.json"), encoding="utf-8"))
        self.assertFalse(state["promoted"])
        self.assertIsNone(state["lastSuccessDate"])

    def test_empty_day_is_ok_not_failure(self):
        raw_dir = os.path.join(self.work_dir, TARGET_DATE, "raw")
        for group in ("a", "b", "c"):
            payload = load_fixture(f"discovery-group-{group}.json")
            for audit in payload["source_audits"]:
                audit["source_status"] = "complete"
                audit["article_count"] = 0
                audit["note"] = "当天无文章"
            payload["articles"] = []
            with open(os.path.join(raw_dir, f"discovery-group_{group}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        feed = self.do_build()
        contracts.validate_feed(feed, TAXONOMY_PATH)
        self.assertTrue(feed["ok"])
        self.assertFalse(feed["degraded"])
        self.assertEqual(feed["items"], [])
        self.assertEqual(feed["stats"]["publishedArticles"], 0)

    def test_corrupted_content_batch_raises(self):
        bad = os.path.join(self.work_dir, TARGET_DATE, "raw", "content-batch-02.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{坏 JSON")
        with self.assertRaises(contracts.ContractError):
            self.do_build()


if __name__ == "__main__":
    unittest.main(verbosity=2)
