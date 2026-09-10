"""公司与产品 Overview 离线测试：固定样本和 mock 模型，不访问网络。"""
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from _tempdir import make_temp_dir
import build_company_overview as overview
from company_index.extraction import extract_articles
from company_index.extraction import build_prompt
from company_index.entities import merge_entities
from company_index.inputs import load_articles
from company_index.output import promote, validate

TX = json.loads((ROOT / "config/taxonomy.json").read_text(encoding="utf-8"))


class MockLLM:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def __call__(self, tx, system, user, **kwargs):
        self.calls.append((system, user, kwargs))
        return next(self.replies)


def item(article_id, title, url, category, summary, dims=None):
    return {"id": article_id, "title": title, "url": url, "source": "测试来源",
            "publishedAt": "2026-09-08T12:00:00+08:00", "summary": summary,
            "classification": {"cat": category, "dims": dims or []}}


class CompanyOverviewTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir("overview-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.snapshot = self.root / "snapshot.json"
        self.feed = self.root / "missing-feed.json"
        self.previous = self.root / "company/current.json"
        self.cache = self.root / "company"
        self.snapshot.write_text(json.dumps({"daily": {"sections": [{"items": [
            item("release-1", "星河发布陪伴产品", "https://example.com/release", "release",
                 "星河科技发布AI陪伴产品小星，面向海外用户提供实时对话服务。" * 3,
                 [{"label": "行业", "value": "AI社交/陪伴"},
                  {"label": "国家/地区", "value": "中国"}]),
            item("interview-1", "星河创始人访谈", "https://example.com/interview", "interview",
                 "星河科技有限公司创始人介绍团队、主营业务和产品小星的发展计划。" * 3),
        ]}]}, "weekly": {"sections": []}}, ensure_ascii=False), encoding="utf-8")

    def build(self, replies):
        mock = MockLLM(replies)
        data = overview.build(self.snapshot, self.feed, self.root / "work", self.previous,
                              self.cache, TX, llm_fn=mock,
                              generated_at="2026-09-09T10:05:00+08:00")
        return data, mock

    def test_all_categories_merge_company_products_and_field_sources(self):
        release = json.dumps({"companies": [{"company_name": "星河科技", "aliases": [],
            "product_names": ["小星"], "country": "中国", "business": "AI陪伴产品",
            "industry_id": "ai_social"}]}, ensure_ascii=False)
        interview = json.dumps({"companies": [{"company_name": "星河科技有限公司",
            "aliases": ["星河科技"], "product_names": ["小星"], "team": "创始团队",
            "industry_id": "ai_social"}]}, ensure_ascii=False)
        data, mock = self.build([release, interview])
        self.assertEqual(len(mock.calls), 2)
        self.assertEqual(data["stats"]["articlesProcessed"], 2)
        self.assertEqual(data["stats"]["companiesTotal"], 1)
        rec = data["companies"][0]
        self.assertEqual(rec["product_names"], ["小星"])
        self.assertEqual(rec["dims"], {"行业": "AI社交/陪伴", "国家/地区": "中国"})
        self.assertEqual(len(rec["sourceArticles"]), 2)
        self.assertEqual(rec["fieldSources"]["product_names"][0]["origin"], "article")
        self.assertEqual({s["articleId"] for s in rec["fieldSources"]["company_name"]},
                         {"release-1", "interview-1"})
        validate(data, TX)

    def test_article_inputs_prioritize_latest_for_bounded_model_calls(self):
        old = item("old", "旧闻", "https://example.com/old", "general", "旧闻摘要")
        new = item("new", "新闻", "https://example.com/new", "general", "新闻摘要")
        old["publishedAt"] = "2026-09-08T12:00:00+08:00"
        new["publishedAt"] = "2026-09-10T09:00:00+08:00"
        self.snapshot.write_text(json.dumps({
            "daily": {"sections": [{"items": [old]}]},
            "weekly": {"sections": [{"items": [new]}]},
        }, ensure_ascii=False), encoding="utf-8")

        articles = load_articles(self.snapshot, self.feed, self.root / "work", TX)

        self.assertEqual([article["id"] for article in articles], ["new", "old"])

    def test_success_cache_prevents_repeat_cost(self):
        replies = [json.dumps({"companies": []}) for _ in range(2)]
        first, mock = self.build(replies)
        self.assertEqual(first["stats"]["modelCalls"], 2)
        second, mock2 = self.build([])
        self.assertEqual(len(mock2.calls), 0)
        self.assertEqual(second["stats"]["cacheHits"], 2)

    def test_prompt_limits_rows_to_core_company_and_uses_company_industry(self):
        system, user = build_prompt(TX, {
            "title": "甲公司拟上市", "sourceName": "测试", "category": "financing",
            "publishedAt": "2026-09-10T10:00:00+08:00",
            "content_text": "甲公司聘请乙证券，丙公司是其投资方。",
        })
        self.assertIn("只保留新闻核心主体", system)
        self.assertIn("财务顾问", system)
        self.assertIn("公司自身业务", system)
        self.assertIn("2026-09-10", user)
        self.assertIn("不能把单轮融资", system)

        articles = [{"id": "a", "title": "甲公司融资", "url": "u", "sourceName": "s",
                     "publishedAt": "2026-09-10", "category": "financing",
                     "dims": {"行业": "AI模型", "国家/地区": "中国"}}]
        extracts = {"a": {"status": "complete", "companies": [{
            "company_name": "甲游戏", "aliases": [], "product_names": ["X9 Ultra", "X9Ultra"],
            "industry_id": "ai_game_content", "country": "美国",
            **{field: None for field in ("founded", "team", "business", "investors",
                                         "total_funding", "valuation")},
        }]}}
        rows = merge_entities(articles, extracts, {}, TX)
        self.assertEqual(rows[0]["dims"], {"行业": "AI游戏内容", "国家/地区": "美国"})
        self.assertEqual(rows[0]["product_names"], ["X9 Ultra"])
        self.assertEqual(len(rows[0]["fieldSources"]["product_names"]), 2)

    def test_failed_extraction_does_not_overwrite_previous(self):
        with self.assertRaisesRegex(ValueError, "全部文章"):
            self.build(["bad", "bad"])

    def test_previous_company_is_retained_and_updated(self):
        initial, _ = self.build([
            json.dumps({"companies": [{"company_name": "星河科技", "product_names": ["小星"],
                "industry_id": "ai_social"}]}),
            json.dumps({"companies": []}),
        ])
        self.previous.parent.mkdir(parents=True, exist_ok=True)
        self.previous.write_text(json.dumps(initial, ensure_ascii=False), encoding="utf-8")
        self.cache.joinpath("extraction_cache.json").unlink()
        updated, _ = self.build([
            json.dumps({"companies": [{"company_name": "星河科技有限公司", "aliases": ["星河科技"],
                "product_names": ["小星Pro"], "valuation": "10亿元", "industry_id": "ai_social"}]}),
            json.dumps({"companies": []}),
        ])
        self.assertEqual(len(updated["companies"]), 1)
        self.assertEqual(updated["companies"][0]["product_names"], ["小星", "小星Pro"])
        self.assertEqual(updated["companies"][0]["valuation"], "10亿元")

    def test_promote_writes_current_archive_and_public(self):
        data, _ = self.build([json.dumps({"companies": []}), json.dumps({"companies": []})])
        current, web = promote(data, self.root / "data", self.root / "public")
        self.assertTrue(current.is_file())
        self.assertTrue(web.is_file())
        self.assertTrue((self.root / "data/archive/2026-09-09.json").is_file())


class CostLimitTest(unittest.TestCase):
    def test_new_article_limit_defers_without_calling(self):
        tx = json.loads(json.dumps(TX))
        tx["companyOverview"]["max_new_articles_per_run"] = 1
        articles = [{"id": str(i), "title": "t", "url": f"u{i}", "sourceName": "s",
                     "publishedAt": "2026-09-09", "category": "general", "dims": {},
                     "content_text": "足够长的固定离线新闻正文" * 4} for i in range(3)]
        root = Path(make_temp_dir("overview-cost-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        mock = MockLLM([json.dumps({"companies": []})])
        results, cost = extract_articles(tx, articles, root / "cache.json", mock)
        self.assertEqual(len(mock.calls), 1)
        self.assertEqual(cost["articlesDeferred"], 2)
        self.assertEqual(sum(r["status"] == "pending" for r in results.values()), 2)


if __name__ == "__main__":
    unittest.main()
