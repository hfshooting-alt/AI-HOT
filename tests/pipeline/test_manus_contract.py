#!/usr/bin/env python3
"""test_manus_contract.py — Manus 信源数据契约离线单测（无网络、无 Manus、无模型调用）。

覆盖方案 §2 的三份契约：
  1. 发现结果（schema v2，source_audits 区分“无文章”与“采集失败”）
  2. 正文批次结果（本地门槛：最小长度/风控页特征/字段一致性）
  3. 规范化 feed（data/manus/current.json：必填字段、枚举、stats 自洽、classification 合法）

另覆盖：稳定 ID（账号+日期+归一化标题）、标题归一化、跨镜像重复 URL 检测。

运行：python -m unittest tests.test_manus_contract -v
"""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from manus_source import contracts  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "manus")
TAXONOMY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config/taxonomy.json")
TARGET_DATE = "2026-08-16"

GROUP_ACCOUNTS = {
    "group_a": ["游戏葡萄", "白鲸出海", "机器之心", "ZFinance", "极客公园", "东西文娱", "娱乐资本论"],
    "group_b": ["FounderPark", "瑞恩资本", "DeepTech深科技", "ZPotential", "华尔街见闻", "量子位", "智东西"],
    "group_c": ["十字路口Crossing", "投资界", "赛博禅心", "elsewhere别处发生", "新智元", "硅星人"],
}


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


class TestDiscoveryContract(unittest.TestCase):
    def test_all_group_fixtures_pass(self):
        for group, accounts in GROUP_ACCOUNTS.items():
            payload = load_fixture(f"discovery-{group.replace('group_', 'group-')}.json")
            # 合法夹具不应抛异常；返回的 complete 文章数与夹具一致
            complete = contracts.validate_discovery(payload, group, TARGET_DATE, accounts)
            want = sum(1 for a in payload["articles"] if a["extraction_status"] == "complete")
            self.assertEqual(len(complete), want)

    def test_source_audit_distinguishes_no_article_from_failure(self):
        payload = load_fixture("discovery-group-a.json")
        audits = {a["account_name"]: a for a in payload["source_audits"]}
        # 白鲸出海：来源成功但当天无文章 —— 不能被误判为漏抓
        self.assertEqual(audits["白鲸出海"]["source_status"], "complete")
        self.assertEqual(audits["白鲸出海"]["article_count"], 0)
        # ZFinance：来源级失败，保留失败原因
        self.assertEqual(audits["ZFinance"]["source_status"], "failed")
        self.assertTrue(audits["ZFinance"]["note"])
        contracts.validate_discovery(payload, "group_a", TARGET_DATE, GROUP_ACCOUNTS["group_a"])

    def test_wrong_group_or_date_rejected(self):
        payload = load_fixture("discovery-group-a.json")
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(payload, "group_b", TARGET_DATE, GROUP_ACCOUNTS["group_a"])
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(payload, "group_a", "2026-08-15", GROUP_ACCOUNTS["group_a"])

    def test_missing_required_fields_rejected(self):
        payload = load_fixture("discovery-group-a.json")
        for field in ("schema_version", "source_group", "target_date", "source_audits", "articles"):
            bad = copy.deepcopy(payload)
            del bad[field]
            with self.assertRaises(contracts.ContractError, msg=field):
                contracts.validate_discovery(bad, "group_a", TARGET_DATE, GROUP_ACCOUNTS["group_a"])

    def test_account_must_appear_exactly_once_in_audits(self):
        base = load_fixture("discovery-group-a.json")
        # 缺一个账号的审计结果 → 拒绝
        missing = copy.deepcopy(base)
        missing["source_audits"] = [a for a in missing["source_audits"] if a["account_name"] != "极客公园"]
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(missing, "group_a", TARGET_DATE, GROUP_ACCOUNTS["group_a"])
        # 重复出现 → 拒绝
        dup = copy.deepcopy(base)
        dup["source_audits"].append(dict(dup["source_audits"][0]))
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(dup, "group_a", TARGET_DATE, GROUP_ACCOUNTS["group_a"])
        # 出现未配置账号 → 拒绝
        extra = copy.deepcopy(base)
        extra["source_audits"].append({"account_name": "未配置账号", "source_status": "complete",
                                       "article_count": 0, "note": None})
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(extra, "group_a", TARGET_DATE, GROUP_ACCOUNTS["group_a"])

    def test_audit_count_matches_complete_articles(self):
        bad = load_fixture("discovery-group-a.json")
        for a in bad["source_audits"]:
            if a["account_name"] == "游戏葡萄":
                a["article_count"] = 99
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(bad, "group_a", TARGET_DATE, GROUP_ACCOUNTS["group_a"])

    def test_complete_article_requires_core_fields_and_matching_date(self):
        base = load_fixture("discovery-group-c.json")
        for mutate in (
            lambda a: a.update(article_url=""),
            lambda a: a.update(title=""),
            lambda a: a.update(account_name=""),
            lambda a: a.update(published_date="2026-08-15"),
        ):
            bad = copy.deepcopy(base)
            mutate(bad["articles"][0])
            with self.assertRaises(contracts.ContractError):
                contracts.validate_discovery(bad, "group_c", TARGET_DATE, GROUP_ACCOUNTS["group_c"])

    def test_failed_article_fields_must_be_null(self):
        bad = load_fixture("discovery-group-a.json")
        for a in bad["articles"]:
            if a["account_name"] == "ZFinance":
                a["article_url"] = "https://news.qq.com/rain/a/should-be-null"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(bad, "group_a", TARGET_DATE, GROUP_ACCOUNTS["group_a"])


class TestDuplicateUrlDetection(unittest.TestCase):
    def test_cross_mirror_duplicate_detected(self):
        payload = load_fixture("discovery-group-b.json")
        dups = contracts.find_duplicate_urls(payload["articles"])
        self.assertEqual(len(dups), 1)
        url, holders = next(iter(dups.items()))
        self.assertEqual(url, "https://www.163.com/dy/article/K1FOUNDER0001.html")
        self.assertEqual(sorted(holders), ["FounderPark", "ZPotential"])

    def test_no_duplicate_in_clean_group(self):
        payload = load_fixture("discovery-group-c.json")
        self.assertEqual(contracts.find_duplicate_urls(payload["articles"]), {})


class TestContentBatchContract(unittest.TestCase):
    def test_fixture_passes_and_statuses_classified(self):
        batch = load_fixture("content-batch.json")
        ok, failed = contracts.validate_content_batch(
            batch, TARGET_DATE,
            {"https://news.qq.com/rain/a/20260816A01VC00000": "AI 视频生成赛道再获数亿元融资"})
        ok_urls = {a["article_url"] for a in ok}
        # 风控页与标题漂移的条目都不得进入加工
        self.assertNotIn("https://news.qq.com/rain/a/20260816A01GEEK000", ok_urls)
        self.assertNotIn("https://news.qq.com/rain/a/20260816A01VC00000", ok_urls)
        self.assertEqual(len(ok), 9)
        self.assertEqual(len(failed), 2)
        reasons = {f["article_url"]: f["reason"] for f in failed}
        self.assertIn("风控", reasons["https://news.qq.com/rain/a/20260816A01GEEK000"])

    def test_truncated_article_keeps_flag(self):
        batch = load_fixture("content-batch.json")
        ok, _ = contracts.validate_content_batch(batch, TARGET_DATE, {})
        truncated = [a for a in ok if a["article_url"].endswith("A01JIQI000")]
        self.assertTrue(truncated and truncated[0]["content_truncated"])

    def test_too_short_content_rejected(self):
        bad = copy.deepcopy(load_fixture("content-batch.json"))
        for a in bad["articles"]:
            if a["account_name"] == "瑞恩资本":
                a["content_text"] = "正文过短。"
        _, failed = contracts.validate_content_batch(bad, TARGET_DATE, {})
        self.assertEqual([f["article_url"] for f in failed if "过短" in f["reason"]],
                         ["https://news.qq.com/rain/a/20260816A01RYAN000"])

    def test_wrong_date_rejected(self):
        bad = copy.deepcopy(load_fixture("content-batch.json"))
        bad["articles"][0]["published_date"] = "2026-08-15"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_content_batch(bad, TARGET_DATE, {})


class TestFeedContract(unittest.TestCase):
    def test_fixture_passes(self):
        contracts.validate_feed(load_fixture("current.json"), TAXONOMY_PATH)

    def test_v2_media_source_passes(self):
        feed = load_fixture("current.json")
        feed["schemaVersion"] = 2
        for item in feed["items"]:
            item.update(sourceType="media", sourceChannel="tencent_syndication",
                        source="腾讯新闻转载：" + item["mpName"])
        contracts.validate_feed(feed, TAXONOMY_PATH)

    def test_relevance_stats_must_be_complete_and_consistent(self):
        feed = load_fixture("current.json")
        feed["stats"].update({"screenedArticles": 10, "relevanceIncludedArticles": 9,
                              "relevanceExcludedArticles": 1, "relevanceFailedArticles": 0,
                              "relevancePendingArticles": 0})
        contracts.validate_feed(feed, TAXONOMY_PATH)
        feed["stats"]["relevanceExcludedArticles"] = 2
        with self.assertRaisesRegex(contracts.ContractError, "不自洽"):
            contracts.validate_feed(feed, TAXONOMY_PATH)

    def test_stats_self_consistency(self):
        bad = copy.deepcopy(load_fixture("current.json"))
        bad["stats"]["publishedArticles"] = len(bad["items"]) + 1
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad, TAXONOMY_PATH)
        bad2 = copy.deepcopy(load_fixture("current.json"))
        bad2["stats"]["fallbackArticles"] = 0  # 实际有 1 条 enrichmentStatus=fallback
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad2, TAXONOMY_PATH)

    def test_bad_classification_rejected(self):
        bad = copy.deepcopy(load_fixture("current.json"))
        bad["items"][0]["classification"]["category"] = "不存在的类别"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad, TAXONOMY_PATH)
        bad2 = copy.deepcopy(load_fixture("current.json"))
        bad2["items"][0]["classification"]["tags"]["industry"] = "越界取值"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad2, TAXONOMY_PATH)

    def test_missing_item_field_rejected(self):
        for field in ("id", "title", "summary", "url", "source", "sourceType", "collector",
                      "mpName", "publishedAt", "publishedPrecision", "contentSha256",
                      "enrichmentStatus", "classification"):
            bad = copy.deepcopy(load_fixture("current.json"))
            del bad["items"][0][field]
            with self.assertRaises(contracts.ContractError, msg=field):
                contracts.validate_feed(bad, TAXONOMY_PATH)

    def test_empty_summary_rejected(self):
        bad = copy.deepcopy(load_fixture("current.json"))
        bad["items"][0]["summary"] = ""
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad, TAXONOMY_PATH)

    def test_full_text_must_not_leak_into_feed(self):
        bad = copy.deepcopy(load_fixture("current.json"))
        bad["items"][0]["content_text"] = "全文不应出现在 feed 中"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad, TAXONOMY_PATH)

    def test_ok_false_with_items_rejected(self):
        bad = copy.deepcopy(load_fixture("current.json"))
        bad["ok"] = False
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad, TAXONOMY_PATH)

    def test_empty_items_with_ok_true_allowed(self):
        feed = load_fixture("current.json")
        feed["items"] = []
        feed["stats"].update({"discoveredArticles": 0, "publishedArticles": 0, "fallbackArticles": 0})
        contracts.validate_feed(feed, TAXONOMY_PATH)  # “当天无文章”不是失败


class TestStableIdAndTitleNorm(unittest.TestCase):
    def test_stable_across_different_urls(self):
        id1 = contracts.stable_article_id("机器之心", "2026-08-16", "大模型推理优化全解析")
        id2 = contracts.stable_article_id("机器之心", "2026-08-16", "大模型推理优化全解析")
        self.assertEqual(id1, id2)
        self.assertTrue(id1.startswith("manus:"))

    def test_whitespace_and_case_insensitive_title(self):
        id1 = contracts.stable_article_id("机器之心", "2026-08-16", "  大模型推理优化全解析 ")
        id2 = contracts.stable_article_id("机器之心", "2026-08-16", "大模型推理优化全解析")
        self.assertEqual(id1, id2)

    def test_different_inputs_yield_different_ids(self):
        base = contracts.stable_article_id("机器之心", "2026-08-16", "标题A")
        self.assertNotEqual(base, contracts.stable_article_id("量子位", "2026-08-16", "标题A"))
        self.assertNotEqual(base, contracts.stable_article_id("机器之心", "2026-08-15", "标题A"))
        self.assertNotEqual(base, contracts.stable_article_id("机器之心", "2026-08-16", "标题B"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
