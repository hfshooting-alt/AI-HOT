import json
import copy
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

    def test_short_upstream_fact_is_reviewed_without_relaxing_manus_body_rule(self):
        item = {**self.item('Grok Bot 现已支持语音'), 'content_text': 'Grok Bot 现已支持语音',
                'evidenceKind': 'upstream_title_summary'}
        calls = []
        def model(*args, **kwargs):
            calls.append(1)
            return json.dumps({'relevant': True, 'reason': '具体产品更新', 'evidence': 'Grok Bot 现已支持语音'})
        self.assertTrue(screen_news.screen_one(TX, item, model)['relevant'])
        item['evidenceKind'] = 'article_body'
        self.assertEqual(screen_news.screen_one(TX, item, model)['status'], 'failed')
        self.assertFalse(screen_news.screen_one(TX, item, model)['modelAttempted'])
        self.assertEqual(len(calls), 1)

    def test_systemic_model_failure_stops_queue_despite_old_cache(self):
        from llm_failures import LLMRequestError
        tx = copy.deepcopy(TX); tx['relevance'] = {**tx.get('relevance', {}), 'concurrency': 1}
        items = [self.item(str(i)) for i in range(20)]
        calls = []
        def model(*args, **kwargs):
            calls.append(1)
            raise LLMRequestError('authentication', 401)
        _, stats = screen_news.screen_items(items, tx, self.tmp/'failed.json', model, max_new_items=20)
        self.assertTrue(stats['circuitStopped'])
        self.assertEqual(len(calls), 1)

    def test_whitespace_difference_returns_actual_source_text(self):
        self.assertEqual(screen_news.source_evidence("AI智能体产品", "发布 AI 智能体产品。"),
                         "AI 智能体产品")

    def test_long_quote_is_verified_before_display_truncation(self):
        item = self.item()
        text = item['content_text'][:120]
        def response(quote):
            return lambda *a, **k: json.dumps({'relevant': True, 'reason': '具体AI产品事件', 'evidence': quote})
        good = screen_news.screen_one(TX, item, response(text))
        self.assertEqual(good['status'], 'complete')
        self.assertEqual(good['evidence'], text[:80])
        bad = screen_news.screen_one(TX, item, response(text + '原文没有的关键结论'))
        self.assertEqual(bad['status'], 'failed')

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
                                 "irrelevant": 1, "failed": 0, "pending": 1,
                                 "modelCalls": 1, "modelSuccesses": 1})
        self.assertEqual(calls[0]["max_tokens"], 180)
        self.assertEqual(calls[0]["operation"], "relevance_screen")
        _, second = screen_news.screen_items(items[:1], TX, self.tmp / "cache.json", model,
                                             max_new_items=0)
        self.assertEqual(second["cacheHits"], 1)
        self.assertEqual(second['modelCalls'], 0)
        self.assertEqual(second['modelSuccesses'], 0)
        self.assertEqual(len(calls), 1)

    def test_completed_result_survives_later_process_interruption(self):
        tx = copy.deepcopy(TX)
        tx['relevance'] = {**tx.get('relevance', {}), 'concurrency': 1}
        items = [self.item('第一条 AI 产品发布'), self.item('第二条 AI 产品发布')]
        cache = self.tmp / 'cache.json'
        calls = []
        def model(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt('simulated interrupted process')
            return json.dumps({'relevant': True, 'reason': 'AI产品', 'evidence': 'AI 智能体产品'})
        with self.assertRaises(KeyboardInterrupt):
            screen_news.screen_items(items, tx, cache, model, max_new_items=2)
        saved = json.loads(cache.read_text(encoding='utf-8'))
        self.assertEqual(saved[screen_news.cache_key(tx, items[0])]['status'], 'complete')
        self.assertNotIn(screen_news.cache_key(tx, items[1]), saved)

    def test_cached_success_is_separate_from_one_new_timeout(self):
        tx = copy.deepcopy(TX); tx.setdefault('relevance', {}).update(concurrency=1)
        items = [self.item('缓存文章'), self.item('本轮新文章')]
        cache = self.tmp / 'mixed.json'
        good = lambda *a, **k: json.dumps({'relevant': True, 'reason': '具体AI事件', 'evidence': 'AI 智能体产品'})
        screen_news.screen_items(items[:1], tx, cache, good)
        saved = json.loads(cache.read_text(encoding='utf8'))
        def timeout(*args, **kwargs):
            raise TimeoutError('private provider message')
        results, stats = screen_news.screen_items(items, tx, cache, timeout)
        self.assertFalse(stats.get('circuitStopped', False))
        self.assertEqual((stats['cacheHits'], stats['modelCalls'], stats['modelSuccesses']), (1, 1, 0))
        self.assertTrue(results[screen_news.item_key(items[0])]['cacheHit'])
        self.assertFalse(results[screen_news.item_key(items[0])]['modelAttempted'])
        self.assertTrue(results[screen_news.item_key(items[1])]['modelAttempted'])
        self.assertEqual(json.loads(cache.read_text(encoding='utf8')), saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
