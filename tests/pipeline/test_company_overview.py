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
        result = next(self.replies)
        try:
            parsed = json.loads(result)
            for company in parsed.get('companies', []):
                company.setdefault('entity_type', 'company')
            return json.dumps(parsed, ensure_ascii=False)
        except (ValueError, AttributeError):
            return result


def item(article_id, title, url, category, summary, dims=None):
    return {"id": article_id, "title": title, "url": url, "source": "测试来源",
            "publishedAt": "2026-09-08T12:00:00+08:00", "summary": summary,
            "classification": {"cat": category, "dims": dims or []}}


class CompanyOverviewTest(unittest.TestCase):
    def test_product_relationships_update_order_without_claiming_ownership(self):
        from company_index.products import merge_updates
        row = {"product_names": [], "fieldSources": {}}
        a = {"id": "old", "publishedAt": "2026-09-13T09:30:00+08:00"}
        b = {"id": "new", "publishedAt": "2026-09-14T09:30:00+08:00"}
        merge_updates(row, {"products": [{"name": "Own", "relationship": "owned", "quote": "开发"}]}, a)
        merge_updates(row, {"products": [{"name": "Grok", "relationship": "integrated", "quote": "集成"}]}, b)
        merge_updates(row, {"products": [{"name": "Grok", "relationship": "integrated", "quote": "集成"}]}, b)
        self.assertEqual(row['product_names'], ['Grok', 'Own'])
        self.assertEqual(len(row['productUpdates']), 2)
        self.assertEqual(row['productUpdates'][0]['relationship'], 'integrated')

    def test_methods_excluded_and_unsupported_ownership_downgraded(self):
        from company_index.extraction import normalize_company
        from company_index.products import normalize
        self.assertIsNone(normalize_company({'company_name': 'RLT', 'entity_type': 'method'}, TX))
        self.assertEqual(normalize([{'name': 'RLT', 'kind': 'method'}]), [])
        result = normalize([{'name': 'Tool', 'kind': 'tool', 'relationship': 'owned', 'quote': '开发'}], {'content_text': '使用工具'})
        self.assertEqual(result[0]['relationship'], 'unknown')
        self.assertEqual(result[0]['name'], 'Tool')

    def test_integration_does_not_prove_same_name_supplier_identity(self):
        from company_index.products import guard_integrated_product_identities
        companies = [
            {"company_name": "A公司", "entity_type": "company", "products": [
                {"name": "T工具", "relationship": "integrated", "quote": "接入虚拟组网工具 T工具"}]},
            {"company_name": "T工具", "entity_type": "company", "products": [
                {"name": "T工具", "relationship": "owned", "quote": "虚拟组网工具 T工具"}]},
        ]
        reviewed = guard_integrated_product_identities(companies)
        self.assertEqual(reviewed[0]['products'][0]['relationship'], 'integrated')
        self.assertEqual(reviewed[1]['entity_type'], 'product')
        self.assertEqual(reviewed[1]['products'][0]['relationship'], 'unknown')
        reviewed[1]['entity_type'] = 'company'
        reviewed[1]['products'][0].update(relationship='owned', quote='T工具公司开发的 T工具')
        self.assertEqual(guard_integrated_product_identities(reviewed)[1]['entity_type'], 'company')

    def test_reprocessing_replaces_only_successful_article_product_contributions(self):
        from company_index.products import replace_article_products
        original = {"companies": [{"product_names": ["错误关联", "历史产品", "失败保留", "官网产品"],
            "fieldSources": {"product_names": [
                {"value": "错误关联", "articleId": "success", "origin": "article"},
                {"value": "历史产品", "articleId": "old", "origin": "article"},
                {"value": "失败保留", "articleId": "failed", "origin": "article"},
                {"value": "官网产品", "articleId": "success", "origin": "research"}]},
            "productUpdates": [{"name": "错误关联", "articleId": "success"}]}]}
        result = replace_article_products(original, {"success"})
        self.assertEqual(result['companies'][0]['product_names'], ['历史产品', '失败保留', '官网产品'])
        self.assertEqual(len(original['companies'][0]['product_names']), 4)
        self.assertEqual(result['companies'][0]['productUpdates'], [])

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

    def test_complete_mode_covers_input_despite_small_default_budget(self):
        import copy
        tx = copy.deepcopy(TX)
        tx['companyOverview']['max_new_articles_per_run'] = 1
        model = MockLLM(['{"companies":[]}', '{"companies":[]}'])
        result = overview.build(self.snapshot, self.feed, self.root/'work', self.previous,
                                self.cache, tx, llm_fn=model, require_complete=True)
        self.assertEqual(result['stats']['articlesComplete'], 2)
        self.assertEqual(result['stats']['articlesDeferred'], 0)
        self.assertEqual(len(model.calls), 2)

    def test_one_failed_company_extraction_blocks_complete_mode(self):
        model = MockLLM(['{"companies":[]}', 'invalid'])
        with self.assertRaisesRegex(ValueError, '公司抽取未完整完成'):
            overview.build(self.snapshot, self.feed, self.root/'work', self.previous,
                           self.cache, TX, llm_fn=model, require_complete=True)
        self.assertFalse(self.previous.exists())

    def test_partial_mode_retains_success_and_exposes_article_failure(self):
        model = MockLLM(['{"companies":[]}', 'invalid'])
        result = overview.build(self.snapshot, self.feed, self.root/'work', self.previous,
                                self.cache, TX, llm_fn=model, require_complete=True, allow_partial=True)
        self.assertEqual(result['stats']['articlesComplete'], 1)
        self.assertEqual(len(result['articleFailures']), 1)
        self.assertTrue(result['articleFailures'][0]['url'].startswith('https://'))

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
        self.assertIn("有实质信息", system)
        self.assertIn("没有实质信息时不新增", system)
        self.assertIn("投资方", system)
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

    def test_profile_date_does_not_advance_on_cached_replay(self):
        initial, _ = self.build([
            json.dumps({'companies': [{'company_name': '星河科技', 'industry_id': 'ai_social'}]}),
            json.dumps({'companies': []}),
        ])
        self.previous.write_text(json.dumps(initial), encoding='utf-8')
        repeated = overview.build(self.snapshot, self.feed, self.root / 'work', self.previous,
            self.cache, TX, llm_fn=MockLLM([]), generated_at='2026-09-14T12:00:00+08:00')
        old, new = initial['companies'][0], repeated['companies'][0]
        self.assertEqual(new['latestReportAt'], '2026-09-08T12:00:00+08:00')
        self.assertEqual(new['profileUpdatedAt'], old['profileUpdatedAt'])

    def test_company_extraction_uses_collected_evidence(self):
        evidence_path = self.root / 'evidence.json'
        evidence_path.write_text(json.dumps([
            {'id': 'release-1', 'url': 'https://example.com/release', 'content_text': '采集原始证据，不是本站生成摘要。' * 8},
            {'id': 'interview-1', 'url': 'https://example.com/interview', 'content_text': '采集原始访谈证据。' * 8},
        ]), encoding='utf-8')
        mock = MockLLM([json.dumps({'companies': []})] * 2)
        overview.build(self.snapshot, self.feed, self.root / 'work', self.previous,
            self.cache, TX, llm_fn=mock, evidence_path=evidence_path)
        self.assertTrue(any('采集原始证据' in user for _, user, _ in mock.calls))
        self.assertFalse(any('面向海外用户提供实时对话服务' in user for _, user, _ in mock.calls))

    def test_mismatched_evidence_blocks_before_model_call(self):
        path = self.root / 'bad-evidence.json'
        path.write_text('[]', encoding='utf-8')
        mock = MockLLM([])
        with self.assertRaisesRegex(ValueError, '证据不一致'):
            overview.build(self.snapshot, self.feed, self.root / 'work', self.previous,
                self.cache, TX, llm_fn=mock, evidence_path=path)
        self.assertEqual(mock.calls, [])

    def test_profile_change_has_separate_update_time(self):
        initial, _ = self.build([
            json.dumps({'companies': [{'company_name': '星河科技', 'industry_id': 'ai_social'}]}),
            json.dumps({'companies': []}),
        ])
        self.previous.write_text(json.dumps(initial), encoding='utf-8')
        self.cache.joinpath('extraction_cache.json').unlink()
        updated = overview.build(self.snapshot, self.feed, self.root / 'work', self.previous,
            self.cache, TX, llm_fn=MockLLM([
                json.dumps({'companies': [{'company_name': '星河科技', 'country': '中国', 'industry_id': 'ai_social'}]}),
                json.dumps({'companies': []}),
            ]), generated_at='2026-09-14T12:00:00+08:00')
        row = updated['companies'][0]
        self.assertEqual(row['latestReportAt'], '2026-09-08T12:00:00+08:00')
        self.assertEqual(row['profileUpdatedAt'], '2026-09-14T12:00:00+08:00')


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
