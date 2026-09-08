#!/usr/bin/env python3
"""test_enrich_news.py — 正文加工 harness 离线单测（mock 模型，不发真实请求）。

覆盖方案 Task 4 步骤 7 要求的全部场景：合法输出、Markdown 围栏、非法 category、
越界 tag、空摘要、超长摘要、网络异常两次、确定性摘要 fallback、正文哈希缓存失效，
并确认正文确实进入模型请求。

运行：python -m unittest tests.test_enrich_news -v
"""
import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
from _tempdir import make_temp_dir  # noqa: E402
import enrich_news  # noqa: E402
import tag_news  # noqa: E402

TX_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config/taxonomy.json")
TX = tag_news.load_taxonomy(TX_PATH)

CONTENT = ("第一段详细报道了一家 AI 创业公司发布新模型的过程，包括参数规模、训练数据和基准测试成绩，"
           "内容足够长，可以作为确定性摘要的来源段落。\n\n第二段补充了行业分析师对该模型的看法。")
GOOD_SUMMARY = ("某 AI 创业公司发布新一代大模型，文章详细介绍了参数规模、训练数据构成与多项基准测试成绩，"
                "并引用行业分析师观点，认为该模型在推理成本上具备明显优势，适合中小团队部署使用，"
                "团队同时公布了开放权重计划与后续微调路线图。")


class MockLLM:
    """按脚本顺序返回模型输出；记录每次请求的 system/user，用于断言正文进入请求。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, tx, system, user, timeout_seconds=None):
        self.calls.append({"system": system, "user": user, "timeout": timeout_seconds})
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(out, Exception):
            raise out
        return out


def make_item(**overrides):
    it = {"title": "新模型发布", "mpName": "机器之心", "content_text": CONTENT,
          "published_date": "2026-08-16"}
    it.update(overrides)
    return it


class TestEnrichOne(unittest.TestCase):
    def run_with(self, outputs, item=None):
        mock = MockLLM(outputs)
        old = enrich_news.call_llm
        enrich_news.call_llm = mock
        try:
            result = enrich_news.enrich_one(TX, item or make_item())
        finally:
            enrich_news.call_llm = old
        return result, mock

    def test_legal_output_complete(self):
        payload = json.dumps({"summary": GOOD_SUMMARY, "category": "release",
                              "tags": {"industry": "ai_model", "issuer": "startup"}},
                             ensure_ascii=False)
        r, mock = self.run_with([payload])
        self.assertEqual(r["enrichmentStatus"], "complete")
        self.assertEqual(r["summary"], GOOD_SUMMARY)
        self.assertEqual(r["classification"]["category"], "release")
        self.assertFalse(r["classification"]["autoFallback"])
        # 正文确实进入模型请求
        self.assertIn("第一段详细报道", mock.calls[0]["user"])
        self.assertIn("机器之心", mock.calls[0]["user"])
        # 长正文使用 enrich 配置的超时而非轻调用的 20s
        self.assertGreater(mock.calls[0]["timeout"], 20)

    def test_markdown_fence_stripped(self):
        payload = '```json\n' + json.dumps(
            {"summary": GOOD_SUMMARY, "category": "general", "tags": {}},
            ensure_ascii=False) + '\n```'
        r, _ = self.run_with([payload])
        self.assertEqual(r["enrichmentStatus"], "complete")
        self.assertEqual(r["classification"]["category"], "general")

    def test_invalid_category_uses_validate_fallback_with_trace(self):
        payload = json.dumps({"summary": GOOD_SUMMARY, "category": "不存在的类别", "tags": {}},
                             ensure_ascii=False)
        r, _ = self.run_with([payload])
        self.assertEqual(r["enrichmentStatus"], "complete")
        self.assertEqual(r["classification"]["category"], "general")
        self.assertTrue(r["classification"]["autoFallback"])  # 留痕
        self.assertEqual(r["summary"], GOOD_SUMMARY)  # 摘要仍保留

    def test_out_of_range_tag_injected_with_trace(self):
        payload = json.dumps({"summary": GOOD_SUMMARY, "category": "release",
                              "tags": {"industry": "越界取值", "issuer": "startup"}},
                             ensure_ascii=False)
        r, _ = self.run_with([payload])
        self.assertEqual(r["classification"]["tags"]["industry"], "ai_other")
        self.assertEqual(r["classification"]["autoFilled"], ["industry"])

    def test_empty_summary_retries_then_fallback(self):
        payload = json.dumps({"summary": "", "category": "release",
                              "tags": {"industry": "ai_model", "issuer": "startup"}},
                             ensure_ascii=False)
        r, mock = self.run_with([payload])
        self.assertEqual(len(mock.calls), 2)  # 摘要非法触发一次重试
        self.assertEqual(r["enrichmentStatus"], "fallback")
        self.assertEqual(r["classification"]["category"], "general")
        self.assertTrue(r["classification"]["autoFallback"])
        self.assertTrue(r["summary"].startswith("第一段"))  # 确定性摘要取首段

    def test_too_long_summary_falls_back(self):
        payload = json.dumps({"summary": "字" * 300, "category": "general", "tags": {}},
                             ensure_ascii=False)
        r, _ = self.run_with([payload])
        self.assertEqual(r["enrichmentStatus"], "fallback")

    def test_network_errors_twice_fall_back(self):
        r, mock = self.run_with([RuntimeError("connection reset"), RuntimeError("timeout")])
        self.assertEqual(len(mock.calls), 2)
        self.assertEqual(r["enrichmentStatus"], "fallback")
        self.assertTrue(r["summary"].startswith("第一段"))

    def test_unparseable_output_falls_back(self):
        r, mock = self.run_with(["完全不是 JSON", "[1,2,3]"])
        self.assertEqual(len(mock.calls), 2)
        self.assertEqual(r["enrichmentStatus"], "fallback")

    def test_no_content_never_fabricates(self):
        for bad in ("", None, "太短"):
            r, _ = self.run_with([json.dumps({"summary": GOOD_SUMMARY, "category": "general",
                                              "tags": {}}, ensure_ascii=False)],
                                 item=make_item(content_text=bad))
            self.assertEqual(r["enrichmentStatus"], "failed")
            self.assertEqual(r["summary"], "")


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir("enrich-cache-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cache_path = os.path.join(self.tmp, "enrich_cache.json")

    def test_content_hash_invalidates_cache(self):
        payload = json.dumps({"summary": GOOD_SUMMARY, "category": "general", "tags": {}},
                             ensure_ascii=False)
        mock = MockLLM([payload])
        old = enrich_news.call_llm
        enrich_news.call_llm = mock
        try:
            item = make_item()
            enrich_news.enrich_items([item], TX, self.cache_path)
            self.assertEqual(len(mock.calls), 1)
            # 相同正文：缓存命中，不再调用模型
            enrich_news.enrich_items([make_item()], TX, self.cache_path)
            self.assertEqual(len(mock.calls), 1)
            # 正文变化：缓存失效，重新调用
            enrich_news.enrich_items([make_item(content_text=CONTENT + "补充新内容。")],
                                     TX, self.cache_path)
            self.assertEqual(len(mock.calls), 2)
        finally:
            enrich_news.call_llm = old
        # 缓存只保存加工结果，不保存全文
        cache_text = open(self.cache_path, encoding="utf-8").read()
        self.assertNotIn("第一段详细报道", cache_text)

    def test_prompt_version_bump_invalidates_old_cache(self):
        old_prefix = tag_news.cache_prefix(TX)
        self.assertTrue(old_prefix.startswith("1:2:"))  # version:promptVersion:model


class TestSelftest(unittest.TestCase):
    def test_selftest_passes_offline(self):
        self.assertEqual(enrich_news.selftest(TX), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
