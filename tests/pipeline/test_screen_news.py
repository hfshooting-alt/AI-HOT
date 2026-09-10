import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from _tempdir import make_temp_dir
import screen_news

TX = json.loads((ROOT / "config/taxonomy.json").read_text(encoding="utf-8"))


class RelevanceScreenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(make_temp_dir("relevance-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def item(self, title="AI 产品发布", body="公司发布了新的 AI 智能体产品，并公开模型能力。"):
        return {"title": title, "mpName": "测试来源", "published_date": "2026-09-10",
                "content_text": body * 10}

    def test_exact_evidence_is_required(self):
        item = self.item()
        good = lambda *a, **k: json.dumps({"relevant": True, "reason": "AI 产品发布",
                                           "evidence": "AI 智能体产品"}, ensure_ascii=False)
        result = screen_news.screen_one(TX, item, good)
        self.assertTrue(result["relevant"])
        bad = lambda *a, **k: json.dumps({"relevant": True, "reason": "AI 产品发布",
                                          "evidence": "正文中不存在的证据"}, ensure_ascii=False)
        self.assertEqual(screen_news.screen_one(TX, item, bad)["status"], "failed")

    def test_whitespace_difference_returns_actual_source_text(self):
        self.assertEqual(screen_news.source_evidence("AI智能体产品", "发布 AI 智能体产品。"),
                         "AI 智能体产品")

    def test_irrelevant_result_is_cached_and_limit_defers_rest(self):
        items = [self.item("普通游戏发布", "游戏公司发布新地图和角色，没有披露智能功能。"),
                 self.item("第二条", "电商平台公布普通促销活动和折扣信息。")]
        calls = []
        def model(*args, **kwargs):
            calls.append(kwargs)
            return json.dumps({"relevant": False, "reason": "没有实质 AI 事件",
                               "evidence": "普通游戏发布"}, ensure_ascii=False)
        results, stats = screen_news.screen_items(items, TX, self.tmp / "cache.json", model,
                                                  max_new_items=1)
        self.assertEqual(stats, {"input": 2, "cacheHits": 0, "calls": 1, "relevant": 0,
                                 "irrelevant": 1, "failed": 0, "pending": 1})
        self.assertEqual(calls[0]["max_tokens"], 180)
        self.assertEqual(calls[0]["operation"], "relevance_screen")
        _, second = screen_news.screen_items(items[:1], TX, self.tmp / "cache.json", model,
                                             max_new_items=0)
        self.assertEqual(second["cacheHits"], 1)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
