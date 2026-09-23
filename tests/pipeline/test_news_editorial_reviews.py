"""Summary review bindings, cache immutability, and fail-closed validation."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import news_editorial_reviews as editorial


SUMMARY = ("文章回顾这家公司的业务发展与团队变化，介绍相关产品的应用场景和当前进展，"
           "并区分早期创业经历、历史并购和本轮行业观察，没有把过去事件写成今天的新发布。")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class NewsEditorialReviews(unittest.TestCase):
    def setUp(self):
        self.item = {"id": "manus:review", "title": "团队与产品回顾",
                     "url": "https://example.com/review", "content_text": "保存的原文正文。"}
        self.result = {"summary": "旧模型摘要。", "summaryOrigin": "model",
                       "classification": {"category": "general", "tags": {}, "autoFallback": False},
                       "enrichmentStatus": "complete", "garenaSelection": {"status": "selected"}}
        self.decision = {"articleId": self.item["id"], "title": self.item["title"],
                         "url": self.item["url"], "contentSha256": digest(self.item["content_text"]),
                         "fromSummarySha256": digest(self.result["summary"]), "toSummary": SUMMARY,
                         "reviewedAt": "2026-09-23T00:30:00+08:00", "reason": "按已保存原文恢复主线。"}

    def test_missing_and_stale_bindings_return_unchanged_deep_copy(self):
        decisions = [[]]
        for key in ("articleId", "title", "url", "contentSha256", "fromSummarySha256"):
            decisions.append([{**self.decision, key: "stale"}])
        for rules in decisions:
            with self.subTest(rules=rules):
                result = editorial.apply_summary_review(self.item, self.result, rules)
                self.assertEqual(result, self.result)
                result["classification"]["tags"]["mutated"] = True
                self.assertEqual(self.result["classification"]["tags"], {})
        no_body = {key: value for key, value in self.item.items() if key != "content_text"}
        self.assertEqual(editorial.apply_summary_review(no_body, self.result, [self.decision]), self.result)
        wrong_digest = {**self.item, "contentSha256": "0" * 64}
        self.assertEqual(editorial.apply_summary_review(wrong_digest, self.result, [self.decision]), self.result)

    def test_valid_default_rule_preserves_classification_selection_and_cache(self):
        before_item, before_result = copy.deepcopy(self.item), copy.deepcopy(self.result)
        with tempfile.TemporaryDirectory() as tmp, patch.object(editorial, "ROOT", Path(tmp)):
            config = Path(tmp) / "config"
            config.mkdir()
            rules_path = config / "quality_review.json"
            rules_path.write_text(json.dumps({"articleSummaryReviews": [self.decision]}), encoding="utf-8")
            (config / "taxonomy.json").write_text("{}", encoding="utf-8")
            rules_before = rules_path.read_bytes()
            result = editorial.apply_summary_review(self.item, self.result)
            self.assertEqual(rules_path.read_bytes(), rules_before)
            metadata = {key: value for key, value in self.item.items() if key != "content_text"}
            metadata["contentSha256"] = self.decision["contentSha256"]
            self.assertEqual(editorial.apply_summary_review(metadata, self.result), result)
        self.assertEqual(result["summary"], SUMMARY)
        self.assertEqual(result["summaryOrigin"], "editorial_review")
        self.assertEqual(result["editorialReview"], {"reviewedAt": self.decision["reviewedAt"],
                         "reason": self.decision["reason"], "origin": "source-grounded-review"})
        for key in ("classification", "enrichmentStatus", "garenaSelection"):
            self.assertEqual(result[key], self.result[key])
        result["classification"]["tags"]["new"] = "value"
        self.assertEqual(self.item, before_item)
        self.assertEqual(self.result, before_result)

    def test_duplicate_exact_matches_are_rejected_without_mutation(self):
        rules = {"articleSummaryReviews": [self.decision, copy.deepcopy(self.decision)]}
        before = copy.deepcopy((self.item, self.result, rules))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            editorial.apply_summary_review(self.item, self.result, rules)
        self.assertEqual((self.item, self.result, rules), before)

    def test_invalid_replacement_is_rejected_by_existing_summary_validator(self):
        for summary in (None, "过短。", "# 标题\n" + SUMMARY, SUMMARY + " https://example.com"):
            with self.subTest(summary=summary):
                decision = {**self.decision, "toSummary": summary}
                before = copy.deepcopy((self.item, self.result, decision))
                with self.assertRaisesRegex(ValueError, "validation"):
                    editorial.apply_summary_review(self.item, self.result, [decision])
                self.assertEqual((self.item, self.result, decision), before)


if __name__ == "__main__":
    unittest.main()
