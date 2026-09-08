#!/usr/bin/env python3
"""test_build_snapshot_manus.py — 快照工作流消费 Manus feed 的离线测试（不访问 API/Manus/模型）。

覆盖 Task 7 步骤 10 要求：加载 feed、去重、归档、summary/classification 保留、
过期降级、空日期成功、旧历史兼容（wechat:* 条目）。

运行：python -m unittest tests.test_build_snapshot_manus -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
from _tempdir import make_temp_dir  # noqa: E402
import build_snapshot  # noqa: E402

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FIXTURE_FEED = os.path.join(os.path.dirname(__file__), "..", "fixtures", "manus", "current.json")
TAXONOMY = os.path.join(PROJECT_ROOT, "config/taxonomy.json")


class TestLoadManusFeed(unittest.TestCase):
    def test_valid_feed_loads_with_sections_and_status(self):
        items, status = build_snapshot.load_manus_feed(FIXTURE_FEED, TAXONOMY,
                                                       max_stale_days=10**5)
        self.assertEqual(len(items), 9)
        self.assertTrue(status["connected"])
        self.assertEqual(status["collector"], "manus")
        self.assertTrue(status["degraded"])  # 夹具含来源级失败
        for it in items:
            self.assertEqual(it["sourceType"], "wechat")
            self.assertIn(it["category"], build_snapshot.SECTIONS)  # 展示版块由现有规则生成
            self.assertTrue(it["summary"])
            self.assertIn("classification", it)  # 语义分类透传，未被覆盖

    def test_summary_and_classification_not_overwritten(self):
        feed = json.load(open(FIXTURE_FEED, encoding="utf-8"))
        want = {it["id"]: (it["summary"], it["classification"]) for it in feed["items"]}
        items, _ = build_snapshot.load_manus_feed(FIXTURE_FEED, TAXONOMY, max_stale_days=10**5)
        for it in items:
            summary, cls = want[it["id"]]
            self.assertEqual(it["summary"], summary)
            self.assertEqual(it["classification"], cls)

    def test_missing_file_degrades(self):
        items, status = build_snapshot.load_manus_feed("nonexistent.json", TAXONOMY)
        self.assertEqual(items, [])
        self.assertFalse(status["connected"])
        self.assertIn("缺失", status["note"])

    def test_corrupted_feed_degrades(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        tmp.write("{坏 JSON")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        items, status = build_snapshot.load_manus_feed(tmp.name, TAXONOMY)
        self.assertEqual(items, [])
        self.assertFalse(status["connected"])

    def test_invalid_schema_degrades(self):
        feed = json.load(open(FIXTURE_FEED, encoding="utf-8"))
        feed["items"][0]["classification"]["category"] = "越界类别"
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(feed, tmp, ensure_ascii=False)
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        items, status = build_snapshot.load_manus_feed(tmp.name, TAXONOMY)
        self.assertEqual(items, [])
        self.assertIn("契约校验失败", status["note"])

    def test_stale_feed_degrades(self):
        items, status = build_snapshot.load_manus_feed(FIXTURE_FEED, TAXONOMY, max_stale_days=0)
        # fixture targetDate=2026-08-16，相对真实今天必然 >=1 天 → 过期
        self.assertEqual(items, [])
        self.assertFalse(status["connected"])
        self.assertIn("过期", status["note"])

    def test_ok_false_degrades(self):
        feed = json.load(open(FIXTURE_FEED, encoding="utf-8"))
        feed["ok"] = False
        feed["items"] = []
        feed["stats"].update({"discoveredArticles": 0, "publishedArticles": 0,
                              "fallbackArticles": 0})
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(feed, tmp, ensure_ascii=False)
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        items, status = build_snapshot.load_manus_feed(tmp.name, TAXONOMY, max_stale_days=10**5)
        self.assertEqual(items, [])
        self.assertIn("ok=false", status["note"])

    def test_empty_items_with_ok_true_is_connected(self):
        feed = json.load(open(FIXTURE_FEED, encoding="utf-8"))
        feed["items"] = []
        feed["degraded"] = False
        feed["stats"].update({"discoveredArticles": 0, "publishedArticles": 0,
                              "fallbackArticles": 0, "failedAccounts": 0,
                              "completeAccounts": 14})
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(feed, tmp, ensure_ascii=False)
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        items, status = build_snapshot.load_manus_feed(tmp.name, TAXONOMY, max_stale_days=10**5)
        self.assertEqual(items, [])
        self.assertTrue(status["connected"])  # “当天无文章”不是信源故障


class TestArchiveKeyCompat(unittest.TestCase):
    def test_manus_items_use_stable_id(self):
        it = {"id": "manus:abc123", "sourceType": "wechat",
              "source": "公众号：机器之心", "title": "标题"}
        self.assertEqual(build_snapshot.archive_key(it), "id:manus:abc123")

    def test_legacy_wechat_items_keep_source_title_key(self):
        it = {"id": "wechat:old-md5", "sourceType": "wechat",
              "source": "公众号：机器之心", "title": "标题"}
        self.assertEqual(build_snapshot.archive_key(it), "wx:公众号：机器之心|标题")

    def test_cross_era_title_dedup_in_upsert(self):
        """旧 wechat 条目与同题 Manus 条目共存时，跨源标题去重仍生效。"""
        tmp = make_temp_dir("snapshot-archive-test-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        legacy = {"id": "wechat:old", "sourceType": "wechat", "source": "公众号：机器之心",
                  "title": "同一篇文章", "url": "https://mp.weixin.qq.com/s?__biz=a&mid=1&sn=x",
                  "publishedAt": "2026-08-16T10:00:00+08:00", "summary": "旧摘要"}
        manus = {"id": "manus:abc123", "sourceType": "wechat", "source": "公众号：机器之心",
                 "title": "同一篇文章", "url": "https://news.qq.com/rain/a/x",
                 "publishedAt": "2026-08-16T12:00:00+08:00", "summary": "新摘要",
                 "classification": {"category": "general", "tags": {},
                                    "autoFallback": False, "autoFilled": []}}
        from datetime import datetime, timedelta, timezone
        now_bj = datetime(2026, 8, 17, 8, 0, tzinfo=timezone(timedelta(hours=8)))
        build_snapshot.upsert_archive(tmp, [legacy, manus], now_bj)
        day = json.load(open(os.path.join(tmp, "2026-08-16.json"), encoding="utf-8"))
        titles = [it["title"] for it in day["items"]]
        self.assertEqual(titles.count("同一篇文章"), 1)  # 同题只保留一条


    def test_manus_item_id_not_prefixed(self):
        """回归：manus:* 稳定 id 不得被包成 aihot:manus:*（否则追踪/去重失效）。"""
        build_snapshot.TAG_TAXONOMY = None
        it = build_snapshot.build_item({"id": "manus:abc123", "title": "t", "summary": "s",
                                        "url": "u", "source": "公众号：机器之心",
                                        "sourceType": "wechat", "category": "行业动态",
                                        "publishedAt": "2026-08-16T12:00:00+08:00"}, 1,
                                       build_snapshot.datetime.now(build_snapshot.BJ))
        self.assertEqual(it["id"], "manus:abc123")


class TestEndToEndWithMockedAPI(unittest.TestCase):
    """main() 全链路：mock aihot API 返回，消费 fixture feed，渲染含 Manus 条目的快照。"""

    def setUp(self):
        self.tmp = make_temp_dir("snapshot-e2e-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_main(self, feed_path):
        from datetime import datetime, timedelta
        recent = (datetime.now(build_snapshot.BJ) - timedelta(hours=1)).isoformat()
        api_items = [{
            "id": "api-1", "title": "aihot 基础资讯一条", "summary": "s",
            "url": "https://example.com/1", "source": "AI HOT",
            "publishedAt": recent, "category": "industry",
            "score": 80,
        }]
        old_fetch = build_snapshot.fetch_items
        build_snapshot.fetch_items = lambda base, since: [dict(i) for i in api_items]
        argv = sys.argv
        sys.argv = ["build_snapshot.py",
                    "--out", os.path.join(self.tmp, "index.html"),
                    "--snapshot-json", os.path.join(self.tmp, "snapshot.json"),
                    "--template", os.path.join(PROJECT_ROOT, "scripts", "templates", "index.template.html"),
                    "--history-template", os.path.join(PROJECT_ROOT, "scripts", "templates", "history.template.html"),
                    "--history-dir", os.path.join(self.tmp, "history"),
                    "--weekly-template", os.path.join(PROJECT_ROOT, "scripts", "templates", "weekly.template.html"),
                    "--weekly-dir", os.path.join(self.tmp, "weekly"),
                    "--archive-dir", os.path.join(self.tmp, "archive"),
                    "--manus-json", feed_path,
                    "--manus-max-stale-days", "100000",
                    "--taxonomy", TAXONOMY,
                    "--no-tags"]
        try:
            return build_snapshot.main()
        finally:
            build_snapshot.fetch_items = old_fetch
            sys.argv = argv
            build_snapshot.TAG_TAXONOMY = None

    def extract_data(self):
        html = open(os.path.join(self.tmp, "index.html"), encoding="utf-8").read()
        start = html.index("const DATA = ") + len("const DATA = ")
        return json.loads(html[start: html.index(";\n", start)])

    def test_snapshot_with_manus_feed(self):
        rc = self.run_main(FIXTURE_FEED)
        self.assertEqual(rc, 0)
        data = self.extract_data()
        # Manus 条目进入归档池：全视图（日报+周报+历史）中可筛出 sourceType=wechat 的 manus 条目
        day_files = os.listdir(os.path.join(self.tmp, "archive"))
        self.assertIn("2026-08-16.json", day_files)
        day = json.load(open(os.path.join(self.tmp, "archive", "2026-08-16.json"),
                             encoding="utf-8"))
        manus_items = [it for it in day["items"] if str(it.get("id") or "").startswith("manus:")]
        self.assertEqual(len(manus_items), 9)
        for it in manus_items:
            self.assertTrue(it["summary"])
            self.assertIn("classification", it)
        # mpStatus 显示 Manus 已接入
        self.assertTrue(data["daily"]["mpStatus"]["connected"])
        self.assertIn("Manus", data["daily"]["mpStatus"]["note"])
        self.assertTrue(data["daily"]["total"] > 0 and data["weekly"]["total"] > 0)

    def test_snapshot_without_feed_still_builds(self):
        rc = self.run_main(os.path.join(self.tmp, "no-such-feed.json"))
        self.assertEqual(rc, 0)
        data = self.extract_data()
        self.assertFalse(data["daily"]["mpStatus"]["connected"])
        self.assertIn("不可用", data["daily"]["mpStatus"]["note"])
        self.assertTrue(data["daily"]["total"] > 0)  # 仅 aihot 数据也能发布


class TestTagArchiveDays(unittest.TestCase):
    """tag_archive_days：当天（未定稿）条目也打标写回，历史定稿日照常补齐。"""

    def _write_day(self, archive_dir: str, date_str: str, finalized: bool, ids: list[str]):
        os.makedirs(archive_dir, exist_ok=True)
        day = {"date": date_str, "finalized": finalized, "finalizedAt": None,
               "updatedAt": None, "items": [
                   {"id": i, "title": f"t-{i}", "summary": "s",
                    "publishedAt": f"{date_str}T12:00:00+08:00"}
                   for i in ids]}
        build_snapshot._save_day_file(
            build_snapshot._day_file_path(archive_dir, date_str), day)

    def test_unfinalized_day_also_tagged(self):
        tmp = make_temp_dir("tag-")
        archive = os.path.join(tmp, "archive")
        self._write_day(archive, "2026-08-20", False, ["a1", "a2"])  # 当天未定稿
        self._write_day(archive, "2026-08-19", True, ["b1"])          # 历史定稿
        all_days = {
            ds: build_snapshot._load_day_file(build_snapshot._day_file_path(archive, ds))
            for ds in ("2026-08-19", "2026-08-20")
        }

        def fake_tag_items(items, tx, cache_path):
            return {build_snapshot.tag_news.item_key(it):
                    {"category": "general", "tags": {}, "autoFallback": False,
                     "autoFilled": []}
                    for it in items}

        orig = build_snapshot.tag_news.tag_items
        build_snapshot.tag_news.tag_items = fake_tag_items
        try:
            changed = build_snapshot.tag_archive_days(
                archive, all_days, {"categories": []},
                os.path.join(tmp, "cache.json"))
        finally:
            build_snapshot.tag_news.tag_items = orig
        self.assertTrue(changed)
        for day in all_days.values():  # 内存中已写回
            for it in day["items"]:
                self.assertEqual(it["classification"]["category"], "general")
        for date_str in all_days:  # 归档文件已落盘
            d = build_snapshot._load_day_file(
                build_snapshot._day_file_path(archive, date_str))
            self.assertTrue(all(it.get("classification") for it in d["items"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
