"""Merge-time semantic guards keep raw caches and rejected evidence intact."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from company_index.entities import merge_entities
from field_value_guard import rejection_reason
from funding.companies import merge_companies

TX = json.loads((ROOT / "config/taxonomy.json").read_text(encoding="utf-8"))


def article(iid, day=20):
    return {"id": iid, "title": iid, "url": "https://example.com/" + iid,
            "publishedAt": f"2026-09-{day:02d}T09:30:00+08:00", "sourceName": "测试来源"}


def extracted(total=None, valuation=None):
    return {"status": "complete", "companies": [{"company_name": "Example AI",
            "total_funding": total, "valuation": valuation}]}


def overview(articles, extracts, previous=None):
    return merge_entities(articles, extracts, previous or {}, TX)


class FieldValueGuardTest(unittest.TestCase):
    def test_explicit_round_and_fund_values_are_not_company_totals(self):
        samples = {
            "3.5亿美元C轮融资": "single_round_not_total",
            "1.5亿美元种子轮融资": "single_round_not_total",
            "2150万美元A轮融资": "single_round_not_total",
            "1000万美元Pre-seed融资": "single_round_not_total",
            "天使融资1000万元": "single_round_not_total",
            "本轮融资总额1亿美元": "single_round_not_total",
            "C轮融资总额3.5亿美元": "single_round_not_total",
            "$350 million Series C round": "single_round_not_total",
            "1.65亿美元首期基金": "fund_size_not_company_total",
            "基金规模3亿美元": "fund_size_not_company_total",
            "$165 million inaugural fund": "fund_size_not_company_total",
        }
        for value, reason in samples.items():
            with self.subTest(value=value):
                self.assertEqual(rejection_reason("total_funding", value), reason)

    def test_explicit_aggregate_bare_amounts_and_ordinary_valuations_survive(self):
        for value in ("累计融资接近1亿美元", "2026 年完成合计近 2 亿美元融资",
                      "累计融资4亿美元，其中C轮3.5亿美元", "共计融资2亿美元",
                      "$400 million total funding, including a Series C round",
                      "50亿美元", "融资总额3亿美元", "由某基金领投的融资1000万元"):
            with self.subTest(value=value):
                self.assertIsNone(rejection_reason("total_funding", value))
        for value in ("估值35亿美元", "投后估值1.65亿美元", "$6 billion valuation", None):
            with self.subTest(value=value):
                self.assertIsNone(rejection_reason("valuation", value))
        self.assertIsNone(rejection_reason("business", "管理1.65亿美元首期基金"))

    def test_explicit_market_cap_is_not_valuation(self):
        for value in ("市值约600亿美元", "$60 billion market cap",
                      "market capitalization of $60 billion", "MARKET CAPITALISATION $60B"):
            with self.subTest(value=value):
                self.assertEqual(rejection_reason("valuation", value), "market_cap_not_valuation")

    def test_both_merges_reject_new_bad_values_and_keep_older_valid_fields(self):
        articles = [article("old", 19), article("new", 20)]
        extracts = {"old": extracted("累计融资1亿美元", "估值5亿美元"),
                    "new": extracted("3.5亿美元C轮融资", "市值约600亿美元")}
        original = copy.deepcopy(extracts)
        for merge in (overview, merge_companies):
            with self.subTest(merge=merge.__name__):
                row = merge(articles, extracts)[0]
                self.assertEqual(row["total_funding"], "累计融资1亿美元")
                self.assertEqual(row["valuation"], "估值5亿美元")
                quarantines = row["fieldQuarantines"]
                self.assertEqual(len(quarantines), 2)
                for quarantine in quarantines:
                    self.assertEqual(quarantine["articleId"], "new")
                    self.assertEqual(quarantine["url"], articles[1]["url"])
                    self.assertEqual(quarantine["publishedAt"], articles[1]["publishedAt"])
                    self.assertEqual(quarantine["origin"], "article")
                    self.assertTrue(quarantine["reason"])
                self.assertEqual({q["originalValue"] for q in quarantines},
                                 {"3.5亿美元C轮融资", "市值约600亿美元"})
                self.assertEqual(merge(articles, extracts)[0], row)
                self.assertEqual(extracts, original)

    def test_rejected_older_gap_fill_is_traced_even_when_newer_value_is_valid(self):
        articles = [article("old", 19), article("new", 20)]
        extracts = {"old": extracted("1.65亿美元首期基金", "市值约600亿美元"),
                    "new": extracted("2026年合计融资2亿美元", "估值10亿美元")}
        for merge in (overview, merge_companies):
            with self.subTest(merge=merge.__name__):
                row = merge(articles, extracts)[0]
                self.assertEqual(row["total_funding"], "2026年合计融资2亿美元")
                self.assertEqual(row["valuation"], "估值10亿美元")
                self.assertEqual({q["articleId"] for q in row["fieldQuarantines"]}, {"old"})

    def test_only_bad_observations_leave_empty_fields_with_evidence(self):
        art = article("single")
        extracts = {"single": extracted("1.65亿美元首期基金", "市值约600亿美元")}
        for merge in (overview, merge_companies):
            with self.subTest(merge=merge.__name__):
                row = merge([art], extracts)[0]
                self.assertIsNone(row["total_funding"])
                self.assertIsNone(row["valuation"])
                self.assertEqual(len(row["fieldQuarantines"]), 2)
                self.assertEqual(row["sourceArticles"][0]["id"], "single")
                self.assertFalse(row.get("fieldSources", {}).get("total_funding"))

    def test_previous_bad_scalars_use_exact_evidence_and_merge_is_idempotent(self):
        art = article("source", 19)
        row = overview([art], {"source": extracted("累计融资1亿美元", "估值5亿美元")})[0]
        # Represent a row produced before the guard, without changing cache data.
        row["total_funding"] = "1.5亿美元种子轮融资"
        row["fieldSources"]["total_funding"][0]["value"] = row["total_funding"]
        row["valuation"] = "市值约600亿美元"
        row["fieldSources"]["valuation"][0]["value"] = row["valuation"]
        previous = {"companies": [row]}
        original = copy.deepcopy(previous)
        clean = overview([], {}, previous)[0]
        self.assertEqual(previous, original)
        self.assertIsNone(clean["total_funding"])
        self.assertIsNone(clean["valuation"])
        self.assertEqual(clean["fieldSources"]["total_funding"], [])
        self.assertEqual(clean["fieldSources"]["valuation"], [])
        self.assertEqual({q["articleId"] for q in clean["fieldQuarantines"]}, {"source"})
        self.assertEqual(overview([], {}, {"companies": [clean]})[0], clean)
        replay = overview([art], {"source": extracted(row["total_funding"], row["valuation"])},
                          {"companies": [clean]})[0]
        self.assertEqual(replay, clean)

    def test_previous_missing_field_source_does_not_invent_attribution(self):
        arts = [article("one", 18), article("two", 19)]
        row = overview(arts, {a["id"]: extracted("50亿美元") for a in arts})[0]
        row["total_funding"] = "1000万美元Pre-seed融资"
        row["fieldSources"].pop("total_funding")
        clean = overview([], {}, {"companies": [row]})[0]
        quarantine = clean["fieldQuarantines"][0]
        self.assertEqual(quarantine["origin"], "previous_record")
        self.assertNotIn("articleId", quarantine)
        self.assertEqual({a["articleId"] for a in quarantine["sourceArticles"]}, {"one", "two"})
        self.assertEqual(overview([], {}, {"companies": [clean]})[0], clean)


if __name__ == "__main__":
    unittest.main()
