#!/usr/bin/env python3
"""test_funding_table.py — 融资动态表格 harness 离线单测（mock 模型/搜索，不发真实请求）。

覆盖：输入装配（snapshot+feed 去重、正文关联）、LLM 抽取（合法/非法输出、无正文、
重试）、公司归一化去重合并、Tavily 搜索补全（无 key 跳过、缓存命中、filledBySearch
留痕）、输出 schema 校验与原子晋升。

运行：python -m unittest tests.test_funding_table -v
"""
import json
import os
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
from _tempdir import make_temp_dir  # noqa: E402
import funding_table  # noqa: E402
import tag_news  # noqa: E402

TX_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config/taxonomy.json")
TX = tag_news.load_taxonomy(TX_PATH)

LONG_CONTENT = ("甲智能科技宣布完成 B 轮融资，金额 3 亿元人民币，投后估值 20 亿元，"
                "由红杉中国领投，老股东 IDG 跟投。公司成立于 2021 年，主营业务为具身智能机器人，"
                "创始团队来自华为，核心成员均有十余年研发经验。") * 2


class MockLLM:
    """按脚本顺序返回模型输出；记录每次请求的 system/user。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, tx, system, user, timeout_seconds=None):
        self.calls.append({"system": system, "user": user})
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(out, Exception):
            raise out
        return out


def snapshot_item(iid, title, url, summary, published_at="2026-08-20T12:00:00+08:00",
                  cat="financing", dims=None):
    return {
        "id": iid, "title": title, "summary": summary, "url": url,
        "source": "公众号：机器之心", "sourceType": "wechat", "mpName": "机器之心",
        "publishedAt": published_at,
        "classification": {
            "cat": cat, "catLabel": "融资动态" if cat == "financing" else "其他",
            "dims": dims if dims is not None else [
                {"label": "行业", "value": "其他AI应用"},
                {"label": "国家/地区", "value": "中国"},
            ],
        },
    }


def feed_item(iid, title, url, summary, published_at="2026-08-21T12:00:00+08:00",
              cat="financing", tags=None):
    return {
        "id": iid, "title": title, "summary": summary, "url": url,
        "source": "公众号：投资界", "sourceType": "wechat", "mpName": "投资界",
        "publishedAt": published_at,
        "classification": {
            "category": cat,
            "tags": tags if tags is not None else {"industry": "ai_other", "region": "cn"},
            "autoFallback": False, "autoFilled": [],
        },
    }


class TestPoolLoading(unittest.TestCase):
    def setUp(self):
        self.dir = make_temp_dir("fund-pool-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, payload):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return path

    def test_snapshot_feed_dedupe_and_filter(self):
        fin = snapshot_item("manus:a", "甲公司融资", "https://u1", "甲公司完成融资")
        other = snapshot_item("manus:b", "乙公司发布", "https://u2", "乙公司发布产品",
                              cat="release")
        snap = {"daily": {"sections": [{"label": "融资动态", "items": [fin, other]}]},
                "weekly": {"sections": [{"label": "融资动态", "items": [fin]}]}}
        feed_fin = feed_item("manus:a", "甲公司融资", "https://u1", "甲公司完成融资（feed 同 id 去重）")
        feed_new = feed_item("manus:c", "丙公司融资", "https://u3", "丙公司完成融资",
                             tags={"industry": "ai_model", "region": "us"})
        snap_path = self.write("web/public/snapshot.json", snap)
        feed_path = self.write("data/manus/current.json",
                               {"ok": True, "items": [feed_fin, feed_new]})
        articles = funding_table.load_articles(snap_path, feed_path,
                                               os.path.join(self.dir, "work", "manus"), TX)
        ids = [a["id"] for a in articles]
        self.assertEqual(ids, ["manus:a", "manus:c"])  # release 被过滤；同 id 去重
        by_id = {a["id"]: a for a in articles}
        self.assertEqual(by_id["manus:a"]["dims"], {"行业": "其他AI应用", "国家/地区": "中国"})
        # feed 条目 tags 枚举 id → 中文 label
        self.assertEqual(by_id["manus:c"]["dims"], {"行业": "AI模型", "国家/地区": "美国"})
        # 无正文索引时退回 title+summary
        self.assertIn("甲公司完成融资", by_id["manus:a"]["content_text"])

    def test_content_index_joins_by_url_and_title(self):
        work = os.path.join(self.dir, "work", "manus")
        batch = {"articles": [
            {"account_name": "机器之心", "article_url": "https://u1", "title": "甲公司融资",
             "content_text": LONG_CONTENT},
            {"account_name": "投资界", "article_url": "https://old", "title": "丙公司融资",
             "content_text": "丙公司的完整正文" * 30},
        ]}
        self.write("work/manus/2026-08-20/raw/content-batch-01.json", batch)
        fin = snapshot_item("manus:a", "甲公司融资", "https://u1", "摘要")
        title_only = snapshot_item("manus:d", "丙公司融资", "https://u4", "丙公司摘要")
        snap = {"daily": {"sections": [{"label": "融资动态", "items": [fin, title_only]}]},
                "weekly": {"sections": []}}
        snap_path = os.path.abspath(self.write("web/public/snapshot.json", snap))
        articles = funding_table.load_articles(
            snap_path, os.path.join(self.dir, "no-feed.json"), work, TX)
        by_title = {a["title"]: a for a in articles}
        self.assertIn("红杉中国", by_title["甲公司融资"]["content_text"])  # url 命中
        self.assertIn("丙公司的完整正文", by_title["丙公司融资"]["content_text"])  # title 命中


class TestExtraction(unittest.TestCase):
    def test_legal_output(self):
        payload = json.dumps({
            "has_funding_info": True,
            "companies": [{
                "company_name": "甲智能科技", "product_name": "甲机器人",
                "founded": "2021年", "country": "中国", "industry": "具身智能",
                "team": "创始团队来自华为", "business": "具身智能机器人",
                "investors": "红杉中国、IDG", "total_funding": "3亿元人民币",
                "valuation": "20亿元", "industry_id": "embodied",
                "company_type_id": "startup", "extra_ignored": "x",
            }],
        }, ensure_ascii=False)
        mock = MockLLM([payload])
        art = {"id": "a", "title": "t", "mpName": "机器之心", "content_text": LONG_CONTENT}
        r = funding_table.extract_one(TX, art, llm_fn=mock)
        self.assertEqual(r["status"], "complete")
        self.assertEqual(r["companies"][0]["company_name"], "甲智能科技")
        self.assertEqual(r["companies"][0]["industry_id"], "具身智能/机器人")
        self.assertEqual(r["companies"][0]["company_type_id"], "初创公司")
        self.assertNotIn("extra_ignored", r["companies"][0])
        self.assertIn("正文", mock.calls[0]["user"])
        self.assertIn("company_name", mock.calls[0]["system"])

    def test_invalid_output_retried_then_failed(self):
        mock = MockLLM(["not json", "still not json"])
        art = {"id": "a", "title": "t", "mpName": "机器之心", "content_text": LONG_CONTENT}
        r = funding_table.extract_one(TX, art, llm_fn=mock)
        self.assertEqual(r["status"], "failed")
        self.assertEqual(mock.calls.__len__(), 2)

    def test_network_error_then_success(self):
        payload = json.dumps({"companies": [{"company_name": "甲"}]}, ensure_ascii=False)
        mock = MockLLM([RuntimeError("boom"), payload])
        art = {"id": "a", "title": "t", "mpName": "机器之心", "content_text": LONG_CONTENT}
        r = funding_table.extract_one(TX, art, llm_fn=mock)
        self.assertEqual(r["status"], "complete")

    def test_short_content_failed_without_llm(self):
        mock = MockLLM(["{}"])
        art = {"id": "a", "title": "t", "mpName": "m", "content_text": "太短"}
        r = funding_table.extract_one(TX, art, llm_fn=mock)
        self.assertEqual(r["status"], "failed")
        self.assertEqual(len(mock.calls), 0)

    def test_bad_company_records_dropped(self):
        payload = json.dumps({"companies": [
            {"company_name": "  "},  # 空名丢弃
            {"company_name": "甲", "founded": 2021},  # 非字符串字段归 None
            "not-a-dict",  # 非对象丢弃
        ]}, ensure_ascii=False)
        mock = MockLLM([payload])
        art = {"id": "a", "title": "t", "mpName": "m", "content_text": LONG_CONTENT}
        r = funding_table.extract_one(TX, art, llm_fn=mock)
        self.assertEqual(len(r["companies"]), 1)
        self.assertIsNone(r["companies"][0]["founded"])

    def test_failed_result_not_cached(self):
        """失败结果不写缓存：配置好 key 后下次运行自动重试。"""
        d = make_temp_dir("fund-nocache-")
        try:
            cache_path = os.path.join(d, "extract-cache.json")
            art = {"id": "a", "title": "t", "mpName": "m", "content_text": LONG_CONTENT}
            funding_table.extract_articles(TX, [art], cache_path,
                                           llm_fn=MockLLM(["not json", "still bad"]))
            with open(cache_path, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), {})  # 无缓存条目
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestMerge(unittest.TestCase):
    def make_articles(self):
        return [
            {"id": "new", "title": "新报道", "url": "u1", "mpName": "甲",
             "publishedAt": "2026-08-21T12:00:00+08:00",
             "dims": {"行业": "AI模型", "国家/地区": "中国"}, "content_text": ""},
            {"id": "old", "title": "旧报道", "url": "u2", "mpName": "乙",
             "publishedAt": "2026-08-19T12:00:00+08:00",
             "dims": {"行业": "其他AI应用", "国家/地区": "中国"}, "content_text": ""},
        ]

    def test_merge_prefers_newer_fills_gaps(self):
        extracts = {
            "new": {"status": "complete", "companies": [
                {"company_name": "甲智能科技有限公司", "valuation": "20亿元",
                 "country": None, "industry_id": "具身智能/机器人", "company_type_id": "初创公司"}]},
            "old": {"status": "complete", "companies": [
                {"company_name": "甲智能科技", "valuation": "旧估值", "country": "中国",
                 "industry_id": "AI模型/基础设施", "company_type_id": "大厂/已上市"}]},
        }
        rows = funding_table.merge_companies(self.make_articles(), extracts)
        self.assertEqual(len(rows), 1)
        rec = rows[0]
        self.assertEqual(rec["valuation"], "20亿元")  # 新文章优先
        self.assertEqual(rec["country"], "中国")  # 旧文章补空
        # dims 由 LLM 枚举 + 源文章 region 构建，新文章优先
        self.assertEqual(rec["dims"]["所属行业"], "具身智能/机器人")
        self.assertEqual(rec["dims"]["公司类型"], "初创公司")
        self.assertEqual(rec["dims"]["国家/地区"], "中国")
        self.assertEqual([sa["id"] for sa in rec["sourceArticles"]], ["new", "old"])

    def test_different_companies_not_merged(self):
        extracts = {
            "new": {"status": "complete", "companies": [{"company_name": "甲科技"}]},
            "old": {"status": "complete", "companies": [{"company_name": "乙科技"}]},
        }
        rows = funding_table.merge_companies(self.make_articles(), extracts)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["company_name"] for r in rows}, {"甲科技", "乙科技"})

    def test_row_sorted_by_latest_article_desc(self):
        extracts = {
            "new": {"status": "complete", "companies": [{"company_name": "甲"}]},
            "old": {"status": "complete", "companies": [{"company_name": "乙"}]},
        }
        rows = funding_table.merge_companies(self.make_articles(), extracts)
        self.assertEqual(rows[0]["company_name"], "甲")  # 最新报道在前


class TestEnumNormalization(unittest.TestCase):
    def test_valid_enum_id_maps_to_label(self):
        rec = funding_table.normalize_company_fields(
            {"company_name": "甲", "industry_id": "game", "company_type_id": "startup"}, TX)
        self.assertEqual(rec["industry_id"], "AI游戏")
        self.assertEqual(rec["company_type_id"], "初创公司")

    def test_invalid_enum_id_falls_back(self):
        rec = funding_table.normalize_company_fields(
            {"company_name": "甲", "industry_id": "not_in_whitelist", "company_type_id": None}, TX)
        self.assertEqual(rec["industry_id"], "其他")
        self.assertEqual(rec["company_type_id"], "其他")

    def test_record_not_dropped_on_invalid_enum(self):
        rec = funding_table.normalize_company_fields(
            {"company_name": "甲", "industry_id": 123}, TX)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["company_type_id"], "其他")


class TestMergeDims(unittest.TestCase):
    def make_articles(self):
        return [
            {"id": "new", "title": "新报道", "url": "u1", "mpName": "甲",
             "publishedAt": "2026-08-21T12:00:00+08:00",
             "dims": {"行业": "AI模型", "国家/地区": "中国"}, "content_text": ""},
            {"id": "old", "title": "旧报道", "url": "u2", "mpName": "乙",
             "publishedAt": "2026-08-19T12:00:00+08:00",
             "dims": {"行业": "其他AI应用", "国家/地区": "美国"}, "content_text": ""},
        ]

    def test_merge_builds_dims_from_enums(self):
        extracts = {
            "new": {"status": "complete", "companies": [
                {"company_name": "甲科技", "industry_id": "具身智能/机器人", "company_type_id": "初创公司",
                 "country": "中国"}]},
            "old": {"status": "complete", "companies": [
                {"company_name": "甲科技", "industry_id": "AI模型/基础设施", "company_type_id": "大厂/已上市",
                 "country": "美国"}]},
        }
        rows = funding_table.merge_companies(self.make_articles(), extracts)
        self.assertEqual(len(rows), 1)
        rec = rows[0]
        # 新文章的非空枚举优先
        self.assertEqual(rec["dims"]["所属行业"], "具身智能/机器人")
        self.assertEqual(rec["dims"]["公司类型"], "初创公司")
        # region 取最新源文章的 dims label
        self.assertEqual(rec["dims"]["国家/地区"], "中国")

    def test_merge_fills_enum_from_older_article_when_newest_is_other(self):
        extracts = {
            "new": {"status": "complete", "companies": [
                {"company_name": "甲科技", "industry_id": "其他", "company_type_id": "其他",
                 "country": "中国"}]},
            "old": {"status": "complete", "companies": [
                {"company_name": "甲科技", "industry_id": "具身智能/机器人", "company_type_id": "初创公司",
                 "country": "美国"}]},
        }
        rows = funding_table.merge_companies(self.make_articles(), extracts)
        rec = rows[0]
        self.assertEqual(rec["dims"]["所属行业"], "具身智能/机器人")
        self.assertEqual(rec["dims"]["公司类型"], "初创公司")

    def test_merge_maps_country_when_region_missing(self):
        articles = [
            {"id": "a1", "title": "新报道", "url": "u1", "mpName": "甲",
             "publishedAt": "2026-08-21T12:00:00+08:00",
             "dims": {}, "content_text": ""},
        ]
        extracts = {
            "a1": {"status": "complete", "companies": [
                {"company_name": "乙科技", "country": "新加坡", "industry_id": "game",
                 "company_type_id": "startup"}]},
        }
        rows = funding_table.merge_companies(articles, extracts)
        self.assertEqual(rows[0]["dims"]["国家/地区"], "东南亚")


class TestSearchFill(unittest.TestCase):
    def setUp(self):
        self.dir = make_temp_dir("fund-search-")
        self.rec = {
            "id": "fund:abc", "company_name": "甲智能科技",
            "product_name": None, "founded": None, "country": "中国",
            "industry": None, "team": None, "business": None, "investors": None,
            "total_funding": None, "valuation": None,
            "dims": {}, "filledBySearch": [], "searchSources": [],
            "sourceArticles": [{"id": "a", "title": "t", "url": "u", "publishedAt": "x", "mpName": "m"}],
        }

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_fill_records_fields_and_sources(self):
        search_results = [{"title": "甲智能科技完成融资", "url": "https://s1",
                           "content": "甲智能科技成立于2021年"}]
        fill = json.dumps({"founded": "2021年", "country": None, "team": None},
                          ensure_ascii=False)
        llm = MockLLM([fill])

        def search_fn(query, max_results):
            self.assertIn("甲智能科技", query)
            return search_results

        funding_table.apply_search_fill(TX, self.rec, search_fn, llm)
        self.assertEqual(self.rec["founded"], "2021年")
        self.assertEqual(self.rec["filledBySearch"], ["founded"])
        self.assertEqual(self.rec["searchSources"], ["https://s1"])
        self.assertEqual(self.rec["country"], "中国")  # 搜索 null 不覆盖已有

    def test_search_failure_skips(self):
        def search_fn(query, max_results):
            raise RuntimeError("network down")

        funding_table.apply_search_fill(TX, self.rec, search_fn, MockLLM(["{}"]))
        self.assertEqual(self.rec["filledBySearch"], [])

    def test_fill_missing_uses_cache(self):
        cache_path = os.path.join(self.dir, "search_cache.json")
        calls = []

        def search_fn(query, max_results):
            calls.append(query)
            return [{"title": "t", "url": "https://s1", "content": "内容"}]

        fill = json.dumps({"founded": "2021年"}, ensure_ascii=False)
        llm = MockLLM([fill])
        n = funding_table.fill_missing_fields(TX, [dict(self.rec)], search_fn, llm, cache_path)
        self.assertEqual(n, 1)
        self.assertEqual(len(calls), 1)

        rec2 = dict(self.rec)
        rec2["founded"] = None
        llm2 = MockLLM(["{}"])  # 不应被调用
        n2 = funding_table.fill_missing_fields(TX, [rec2], search_fn, llm2, cache_path)
        self.assertEqual(n2, 0)
        self.assertEqual(len(calls), 1)  # 缓存命中不再搜索
        self.assertEqual(rec2["founded"], "2021年")
        self.assertEqual(rec2["filledBySearch"], ["founded"])


class TestBuildAndPromote(unittest.TestCase):
    def setUp(self):
        self.dir = make_temp_dir("fund-build-")
        self.snapshot_path = os.path.abspath(
            os.path.join(self.dir, "public", "snapshot.json"))
        os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
        with open(self.snapshot_path, "w", encoding="utf-8") as f:
            snap = {
                "daily": {"sections": [{"label": "融资动态", "items": [
                    snapshot_item("manus:a", "甲公司融资", "https://u1", LONG_CONTENT)]}]},
                "weekly": {"sections": []},
            }
            json.dump(snap, f, ensure_ascii=False)
        self.feed_path = os.path.join(self.dir, "no-feed.json")
        self.cache_dir = os.path.join(self.dir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def build(self, llm_fn, search_fn=None, skip_search=False):
        return funding_table.build_funding_table(
            self.snapshot_path, self.feed_path, os.path.join(self.dir, "work"),
            TX, self.cache_dir,
            llm_fn=llm_fn, search_fn=search_fn, skip_search=skip_search,
            generated_at="2026-08-21T10:00:00+08:00")

    def test_build_without_key_skips_search(self):
        payload = json.dumps({"companies": [
            {"company_name": "甲智能科技", "valuation": "20亿元"}]}, ensure_ascii=False)
        # 抹除 TAVILY_API_KEY，确保 make_search_fn 返回 None
        with patch.dict(os.environ, {"TAVILY_API_KEY": ""}, clear=False):
            table = self.build(MockLLM([payload]), search_fn=None, skip_search=False)
        # search_fn=None 且 make_search_fn 无 key → 跳过搜索
        self.assertIn("未配置 TAVILY_API_KEY", table["searchNote"])
        self.assertEqual(table["stats"]["articlesProcessed"], 1)
        self.assertEqual(table["stats"]["companiesTotal"], 1)
        rec = table["companies"][0]
        self.assertTrue(rec["id"].startswith("fund:"))
        self.assertEqual(rec["sourceArticles"][0]["url"], "https://u1")
        # 无 key 时不发起搜索
        self.assertEqual(table["stats"]["companiesSearched"], 0)

    def test_build_with_search_fn(self):
        payload = json.dumps({"companies": [{"company_name": "甲智能科技"}]},
                             ensure_ascii=False)
        fill = json.dumps({"founded": "2021年", "country": "中国"}, ensure_ascii=False)

        def search_fn(query, max_results):
            return [{"title": "t", "url": "https://s1", "content": "甲智能成立于2021年"}]

        mock = MockLLM([payload, fill])
        table = self.build(mock, search_fn=search_fn)
        self.assertEqual(table["stats"]["companiesSearched"], 1)
        rec = table["companies"][0]
        self.assertEqual(rec["founded"], "2021年")
        self.assertEqual(rec["filledBySearch"], ["founded", "country"])
        self.assertEqual(rec["searchSources"], ["https://s1"])

    def test_extraction_cache_reused(self):
        payload = json.dumps({"companies": [{"company_name": "甲智能科技"}]},
                             ensure_ascii=False)
        mock = MockLLM([payload])
        funding_table.build_funding_table(
            self.snapshot_path, self.feed_path, os.path.join(self.dir, "work"),
            TX, self.cache_dir, llm_fn=mock, skip_search=True,
            generated_at="2026-08-21T10:00:00+08:00")
        # 第二次构建：缓存命中，不再调用模型
        mock2 = MockLLM(["{}"])
        table = funding_table.build_funding_table(
            self.snapshot_path, self.feed_path, os.path.join(self.dir, "work"),
            TX, self.cache_dir, llm_fn=mock2, skip_search=True,
            generated_at="2026-08-21T11:00:00+08:00")
        self.assertEqual(len(mock2.calls), 0)
        self.assertEqual(table["stats"]["companiesTotal"], 1)

    def test_validate_rejects_bad_dims(self):
        payload = json.dumps({"companies": [{"company_name": "甲智能科技"}]},
                             ensure_ascii=False)
        table = self.build(MockLLM([payload]), skip_search=True)
        bad = json.loads(json.dumps(table, ensure_ascii=False))
        bad["companies"][0]["dims"] = {"不存在的维度": "中国"}
        with self.assertRaises(ValueError):
            funding_table.validate_table(bad, TX)

    def test_validate_accepts_funding_dims(self):
        payload = json.dumps({"companies": [
            {"company_name": "甲智能科技", "industry_id": "game",
             "company_type_id": "startup"}]}, ensure_ascii=False)
        table = self.build(MockLLM([payload]), skip_search=True)
        rec = table["companies"][0]
        self.assertEqual(rec["dims"]["所属行业"], "AI游戏")
        self.assertEqual(rec["dims"]["公司类型"], "初创公司")
        # 校验应通过（融资专属维度在合法集中）
        funding_table.validate_table(table, TX)

    def test_validate_rejects_missing_source(self):
        payload = json.dumps({"companies": [{"company_name": "甲智能科技"}]},
                             ensure_ascii=False)
        table = self.build(MockLLM([payload]), skip_search=True)
        bad = json.loads(json.dumps(table, ensure_ascii=False))
        bad["companies"][0]["sourceArticles"] = []
        with self.assertRaises(ValueError):
            funding_table.validate_table(bad, TX)

    def test_promote_atomic_write(self):
        payload = json.dumps({"companies": [{"company_name": "甲智能科技"}]},
                             ensure_ascii=False)
        table = self.build(MockLLM([payload]), skip_search=True)
        data_dir = os.path.join(self.dir, "data", "funding")
        public_dir = os.path.join(self.dir, "public")
        current, web = funding_table.promote_table(table, data_dir, public_dir)
        self.assertTrue(os.path.exists(current))
        self.assertTrue(os.path.exists(web))
        with open(web, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["schemaVersion"], 1)
        archive = os.path.join(data_dir, "archive", "2026-08-21.json")
        self.assertTrue(os.path.exists(archive))


class TestConfigCompatibility(unittest.TestCase):
    def test_funding_cfg_and_search_cfg_ignore_new_dims(self):
        """taxonomy.json funding 节点新增枚举块后，funding_cfg / search_cfg 仍能正常读取。"""
        cfg = funding_table.funding_cfg(TX)
        self.assertIn("industry_dim", cfg)
        self.assertIn("company_type_dim", cfg)
        self.assertEqual(cfg["content_input_chars"], 16000)
        scfg = funding_table.search_cfg(TX)
        self.assertEqual(scfg["provider"], "tavily")


if __name__ == "__main__":
    unittest.main()
