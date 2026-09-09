"""十点窗口的边界、跨日正文、feed 与日报联调；不调用外部 API。"""
from copy import deepcopy
from datetime import datetime
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from _tempdir import make_temp_dir
import build_manus_feed
import build_snapshot
import run_pipeline
from automation import runner as orchestration
from manus_source import contracts
from manus_source.pipeline import ContentPipeline
from manus_source.runner import run_discovery
from manus_source.window import BJ, ten_am_window, latest_cutoff_date, timestamp, contains

END_DATE = "2026-09-09"
WINDOW = ten_am_window(END_DATE)
CONFIG = json.loads((ROOT / "config/manus_sources.json").read_text(encoding="utf-8"))["groups"]
TAXONOMY = ROOT / "config/taxonomy.json"


def fixture_groups():
    groups = {}
    times = [WINDOW["start"], "2026-09-08T23:59:00+08:00", "2026-09-09T09:59:59+08:00"]
    for (group, accounts), instant in zip(CONFIG.items(), times):
        source = accounts[0]
        groups[group] = {"schema_version": 3, "source_group": group, "target_date": END_DATE,
            "collectionWindow": WINDOW,
            "source_audits": [{"account_name": a["account_name"], "source_status": "complete",
                "article_count": int(a == source), "note": None} for a in accounts],
            "articles": [{"account_name": source["account_name"], "source_platform": source["platform"],
                "source_home_url": source["home_url"], "title": f"窗口新闻 {group}",
                "article_url": f"https://example.com/{group}", "published_date": instant[:10],
                "published_at": instant, "author": None, "extraction_status": "complete", "note": None}]}
    return groups


def fake_enrich(items, tx, cache_path):
    import enrich_news
    return {enrich_news.enrich_item_key(i): {"summary": "固定样本摘要", "enrichmentStatus": "complete",
        "classification": {"category": "general", "tags": {}, "autoFallback": False}} for i in items}


class TestTenAm(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir("ten-am-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_latest_completed_cutoff_is_stable_after_delay(self):
        for hour, expected in [(9, "2026-09-08"), (10, END_DATE), (15, END_DATE), (23, END_DATE)]:
            self.assertEqual(latest_cutoff_date(datetime(2026, 9, 9, hour, tzinfo=BJ)), expected)
        self.assertEqual(ten_am_window("2026-01-01")["start"], "2025-12-31T10:00:00+08:00")

    def test_boundaries_and_timezone(self):
        self.assertTrue(contains(WINDOW, WINDOW["start"]))
        self.assertFalse(contains(WINDOW, WINDOW["end"]))
        self.assertTrue(contains(WINDOW, "2026-09-08T02:00:00Z"))
        self.assertFalse(contains(WINDOW, "2026-09-08T09:59:59+08:00"))
        for invalid in ("2026-09-08", "2026-09-08T11:00:00"):
            with self.assertRaises(ValueError):
                timestamp(invalid)

    def test_discovery_rejects_unknown_time_outside_window_and_date_mismatch(self):
        groups = fixture_groups()
        payload = groups["group_a"]
        accounts = [a["account_name"] for a in CONFIG["group_a"]]
        contracts.validate_discovery(payload, "group_a", END_DATE, accounts)
        for value in (None, "2026-09-08", WINDOW["end"], "2026-09-08T09:59:59+08:00"):
            bad = deepcopy(payload)
            bad["articles"][0]["published_at"] = value
            with self.assertRaises(contracts.ContractError):
                contracts.validate_discovery(bad, "group_a", END_DATE, accounts)
        bad = deepcopy(payload)
        bad["articles"][0]["published_date"] = END_DATE
        with self.assertRaises(contracts.ContractError):
            contracts.validate_discovery(bad, "group_a", END_DATE, accounts)

    def test_discovery_uses_one_task_and_attaches_fixed_window(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        payload = fixture_groups()["group_a"]
        client = Mock()
        client.create_crawl_task.return_value = SimpleNamespace(task_id="fake", task_url="https://example.com/fake")
        client.wait_for_structured_result.return_value = deepcopy(payload)
        result = run_discovery(client, "group_a", END_DATE, "fixed prompt", [a["account_name"] for a in CONFIG["group_a"]], WINDOW)
        self.assertEqual(client.create_crawl_task.call_count, 1)
        self.assertEqual(result["collectionWindow"], WINDOW)
        kwargs = client.create_crawl_task.call_args.kwargs
        self.assertIn(WINDOW["start"], kwargs["task_brief"])
        self.assertIn("published_at", kwargs["output_schema"]["properties"]["articles"]["items"]["required"])

    def make_feed(self):
        groups = fixture_groups()
        work = self.root / "work/manus/ten-am"
        raw = work / END_DATE / "raw"
        raw.mkdir(parents=True)
        for group, payload in groups.items():
            (raw / f"discovery-{group}.json").write_text(json.dumps(payload), encoding="utf-8")
        class Provider:
            calls = 0
            def fetch_content(self, batch, batch_index):
                self.calls += 1
                return {"target_date": END_DATE, "articles": [{**a, "content_status": "complete",
                    "content_text": "完整样本正文用于离线测试。" * 30, "content_truncated": False} for a in batch]}
        provider = Provider()
        pipeline = ContentPipeline(provider, "limit {{MAX_CONTENT_CHARS}}", END_DATE, work, batch_size=4)
        result = pipeline.run(groups)
        self.assertEqual(len(result.ok_articles), 3)
        self.assertEqual(provider.calls, 1)
        pipeline.run(groups)
        self.assertEqual(provider.calls, 1)
        feed = build_manus_feed.build(END_DATE, work, ROOT / "config/manus_sources.json", TAXONOMY,
            enrich_fn=fake_enrich, generated_at="2026-09-09T11:00:00+08:00",
            cache_path=self.root / "cache.json", window=WINDOW)
        contracts.validate_feed(feed, str(TAXONOMY))
        return feed

    def test_cross_date_content_resume_and_feed_keep_actual_timestamps(self):
        feed = self.make_feed()
        self.assertEqual(feed["collectionWindow"], WINDOW)
        self.assertEqual({i["publishedAt"] for i in feed["items"]},
            {a["published_at"] for d in fixture_groups().values() for a in d["articles"]})
        bad = deepcopy(feed)
        bad["items"][0]["publishedPrecision"] = "date"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_feed(bad, str(TAXONOMY))

    def test_snapshot_daily_and_new_archive_use_same_window(self):
        feed = self.make_feed()
        feed_path = self.root / "feed.json"
        feed_path.write_text(json.dumps(feed), encoding="utf-8")
        upstream = [{"id": f"api-{i}", "title": f"上游样本 {i}", "publishedAt": t,
            "url": f"https://example.com/api-{i}", "category": "industry", "summary": "上游摘要"}
            for i, t in enumerate([WINDOW["start"], WINDOW["end"], "2026-09-08T09:00:00+08:00"])]
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 9, 11, tzinfo=BJ).astimezone(tz) if tz else datetime(2026, 9, 9, 11)
        argv = ["build_snapshot.py", "--window-date", END_DATE, "--no-tags",
            "--out", str(self.root / "index.html"), "--snapshot-json", str(self.root / "snapshot.json"),
            "--manus-json", str(feed_path), "--archive-dir", str(self.root / "archive"),
            "--history-dir", str(self.root / "history"), "--weekly-dir", str(self.root / "weekly"),
            "--taxonomy", str(TAXONOMY)]
        with patch.object(sys, "argv", argv), patch.object(build_snapshot, "datetime", FixedDateTime), \
             patch.object(build_snapshot, "fetch_items", return_value=upstream) as fetch, \
             patch.object(build_snapshot, "fetch_hot_topics", return_value={"items": []}):
            self.assertEqual(build_snapshot.main(), 0)
        self.assertEqual(fetch.call_args.args[1], timestamp(WINDOW["start"]))
        snapshot = json.loads((self.root / "snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["daily"]["total"], 4)
        self.assertEqual(snapshot["daily"]["range"]["endAt"], WINDOW["end"])
        all_ids = [i["id"] for f in (self.root / "archive").glob("*.json")
                   for i in json.loads(f.read_text(encoding="utf-8"))["items"]]
        self.assertNotIn("api-1", all_ids)
        self.assertNotIn("api-2", all_ids)

    def test_cli_plan_and_resume_storage_distinguish_legacy_runs(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(run_pipeline.main(["run", "--dry-run", "--date", END_DATE]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["collectionWindow"], WINDOW)
        self.assertIn("--ten-am", plan["stages"][0]["command"])
        self.assertIn("--window-date", plan["stages"][3]["command"])
        orchestration.run(self.root, END_DATE, ["discovery"], ten_am=True, execute=lambda _: 1)
        latest = self.root / "work/runs" / END_DATE / "ten-am/latest.json"
        self.assertTrue(latest.exists())
        rid = json.loads(latest.read_text())["runId"]
        state = json.loads((latest.parent / rid / "state.json").read_text())
        self.assertEqual(state["collectionWindow"], WINDOW)
        self.assertFalse((latest.parent.parent / "latest.json").exists())


if __name__ == "__main__":
    unittest.main()
