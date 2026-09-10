#!/usr/bin/env python3
"""test_tag_validation.py — tag_news 校验链离线单测（无网络）。

运行：python3 tests/test_tag_validation.py
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import tag_news  # noqa: E402

TX_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config/taxonomy.json")
TX = tag_news.load_taxonomy(TX_PATH)


class TestParseOutput(unittest.TestCase):
    def test_bare_json(self):
        d = tag_news.parse_output('{"category": "paper", "tags": {}}')
        self.assertEqual(d["category"], "paper")

    def test_markdown_fence(self):
        d = tag_news.parse_output('```json\n{"category": "paper", "tags": {}}\n```')
        self.assertEqual(d["category"], "paper")

    def test_json_embedded_in_text(self):
        d = tag_news.parse_output('结果如下 {"category":"general","tags":{}} 以上')
        self.assertEqual(d["category"], "general")

    def test_garbage_returns_none(self):
        self.assertIsNone(tag_news.parse_output("无法分类"))
        self.assertIsNone(tag_news.parse_output(""))
        self.assertIsNone(tag_news.parse_output("[1,2,3]"))


class TestValidate(unittest.TestCase):
    def test_valid_financing_passthrough(self):
        r = tag_news.validate(TX, {"category": "financing",
                                   "tags": {"industry": "ai_model", "region": "cn"}})
        self.assertEqual(r["category"], "financing")
        self.assertEqual(r["tags"], {"industry": "ai_model", "region": "cn"})
        self.assertFalse(r["autoFallback"])
        self.assertEqual(r["autoFilled"], [])

    def test_invalid_category_falls_back_to_general(self):
        r = tag_news.validate(TX, {"category": "不存在的类别", "tags": {}})
        self.assertEqual(r["category"], "general")
        self.assertEqual(r["tags"], {})
        self.assertTrue(r["autoFallback"])

    def test_missing_or_malformed_input_falls_back(self):
        for bad in (None, {}, {"category": 123}, {"category": None}):
            r = tag_news.validate(TX, bad)
            self.assertEqual(r["category"], "general")
            self.assertTrue(r["autoFallback"])

    def test_unbound_dim_dropped_and_invalid_value_fallback(self):
        # release 只绑定 industry+issuer；company 越界应丢弃；industry 非法值注入 fallback
        r = tag_news.validate(TX, {"category": "release",
                                   "tags": {"industry": "xxx", "company": "tencent"}})
        self.assertEqual(r["category"], "release")
        self.assertNotIn("company", r["tags"])
        self.assertEqual(r["tags"]["industry"], "ai_other")
        self.assertEqual(r["tags"]["issuer"], "other")  # 缺失 → fallback
        self.assertEqual(sorted(r["autoFilled"]), ["industry", "issuer"])

    def test_missing_dim_value_injected_with_trace(self):
        r = tag_news.validate(TX, {"category": "bigtech", "tags": {"company": "openai"}})
        self.assertEqual(r["tags"]["company"], "openai")
        self.assertEqual(r["tags"]["change_type"], "other")
        self.assertEqual(r["autoFilled"], ["change_type"])

    def test_paper_and_general_force_empty_tags(self):
        r = tag_news.validate(TX, {"category": "paper", "tags": {"industry": "ai_model"}})
        self.assertEqual(r["tags"], {})
        self.assertFalse(r["autoFallback"])
        r2 = tag_news.validate(TX, {"category": "general", "tags": {"region": "cn"}})
        self.assertEqual(r2["tags"], {})

    def test_tags_not_dict_treated_as_missing(self):
        r = tag_news.validate(TX, {"category": "interview", "tags": "industry:ai_model"})
        self.assertEqual(r["tags"], {"industry": "ai_other", "interviewee": "other"})
        self.assertEqual(sorted(r["autoFilled"]), ["industry", "interviewee"])

    def test_whitespace_normalized(self):
        r = tag_news.validate(TX, {"category": " release ",
                                   "tags": {"industry": " game_engine ", "issuer": "startup"}})
        self.assertEqual(r["category"], "release")
        self.assertEqual(r["tags"]["industry"], "game_engine")
        self.assertEqual(r["autoFilled"], [])


class TestPromptAndContract(unittest.TestCase):
    def test_prompt_contains_priority_order(self):
        system, _ = tag_news.build_prompt(TX, "测试标题", "测试摘要")
        idx = [system.find(c) for c in ["financing", "release", "bigtech",
                                        "paper", "interview", "general"]]
        self.assertTrue(all(i >= 0 for i in idx))
        self.assertEqual(idx, sorted(idx))  # 优先级链顺序与配置一致

    def test_taxonomy_selfcheck(self):
        self.assertEqual(TX["priority"], [c["id"] for c in TX["categories"]])
        self.assertEqual(TX["fallbackCategoryId"], "general")

    def test_item_key_stability_for_wechat(self):
        it = {"id": "wechat:abcd", "source": "公众号：机器之心", "title": "测试标题"}
        it2 = {"id": "wechat:ffff", "source": "公众号：机器之心", "title": "测试标题"}
        self.assertEqual(tag_news.item_key(it), tag_news.item_key(it2))  # 同文不同签名链接 → 同键

    def test_to_display_labels(self):
        r = {"category": "financing", "tags": {"industry": "ai_model", "region": "cn"},
             "autoFallback": False, "autoFilled": []}
        d = tag_news.to_display(TX, r)
        self.assertEqual(d["catLabel"], "融资动态")
        self.assertEqual([x["value"] for x in d["dims"]], ["AI模型", "中国"])


class TestBatchCostLimit(unittest.TestCase):
    def test_completed_result_is_cached_after_deadline(self):
        tx = json.loads(json.dumps(TX))
        tx["model"].update(max_new_items_per_run=1, budget_seconds=-1)
        with tempfile.TemporaryDirectory() as folder, patch.object(
                tag_news, "tag_one", return_value={"category": "general", "tags": {}}) as call:
            path = os.path.join(folder, "cache.json")
            items = [{"id": "finished", "title": "test"}]
            self.assertEqual(len(tag_news.tag_items(items, tx, path)), 1)
            self.assertEqual(len(tag_news.tag_items(items, tx, path)), 1)
            self.assertEqual(call.call_count, 1)

    def test_only_submits_configured_number_of_new_items(self):
        tx = json.loads(json.dumps(TX))
        tx["model"]["max_new_items_per_run"] = 1
        items = [{"id": f"i-{i}", "title": f"新闻 {i}", "summary": "摘要"}
                 for i in range(3)]
        with tempfile.TemporaryDirectory() as folder, patch.object(
                tag_news, "tag_one",
                return_value={"category": "general", "tags": {},
                              "autoFallback": False, "autoFilled": []}) as call:
            result = tag_news.tag_items(items, tx, os.path.join(folder, "cache.json"))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
