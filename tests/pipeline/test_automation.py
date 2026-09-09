"""离线验证失败保护、缓存恢复、编排与发布回滚。"""
import contextlib
import io
import json
import os
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
import enrich_news
import funding_table
import build_company_overview
import run_pipeline
from automation import doctor, runner, publish
from manus_source.contracts import ContractError

TX = json.loads((ROOT / "config/taxonomy.json").read_text(encoding="utf-8"))


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir("automation-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "config").mkdir()
        for name in ("taxonomy.json", "manus_sources.json"):
            shutil.copyfile(ROOT / "config" / name, self.root / "config" / name)
        for rel in publish.ALLOWED:
            folder = self.root / rel
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "sentinel.txt").write_text("old", encoding="utf-8")

    def test_all_extraction_failed_is_rejected_but_real_empty_result_is_valid(self):
        snapshot = self.root / "web/public/snapshot.json"
        snapshot.write_text(json.dumps({"daily": {"sections": [{"items": [{
            "id": "a", "title": "融资报道", "summary": "完整融资正文" * 40,
            "classification": {"cat": "financing"}, "url": "https://example.com/a"}]}]},
            "weekly": {"sections": []}}), encoding="utf-8")
        def fail(*args, **kwargs):
            raise RuntimeError("offline simulated failure")
        args = (snapshot, self.root / "missing.json", self.root / "work", TX, self.root / "data/funding")
        with self.assertRaisesRegex(ValueError, "全部抽取失败"):
            funding_table.build_funding_table(*args, llm_fn=fail, skip_search=True)
        table = funding_table.build_funding_table(*args, llm_fn=lambda *a, **k: '{"companies": []}', skip_search=True)
        self.assertEqual(table["companies"], [])
        self.assertEqual((self.root / "data/funding/sentinel.txt").read_text(), "old")

    def test_failure_feed_cannot_be_published(self):
        for discovered, failed in [(3, 0), (0, 2)]:
            with self.assertRaises(ContractError):
                build_manus_feed.validate_publishable({"items": [], "stats": {
                    "discoveredArticles": discovered, "failedAccounts": failed}})
        build_manus_feed.validate_publishable({"items": [], "stats": {
            "discoveredArticles": 0, "failedAccounts": 0}})

    def test_legacy_fallback_retries_then_success_is_cached(self):
        item = {"title": "报道", "content_text": "真实正文" * 50}
        key = enrich_news.enrich_cache_key(TX, item)
        cache = self.root / "cache.json"
        cache.write_text(json.dumps({key: {"enrichmentStatus": "fallback"}}), encoding="utf-8")
        with patch.object(enrich_news, "enrich_one", side_effect=[
            {"enrichmentStatus": "fallback"}, {"enrichmentStatus": "complete", "summary": "ok"}]) as fn:
            enrich_news.enrich_items([item], TX, str(cache))
            self.assertNotIn(key, json.loads(cache.read_text()))
            enrich_news.enrich_items([item], TX, str(cache))
            enrich_news.enrich_items([item], TX, str(cache))
        self.assertEqual(fn.call_count, 2)

    def test_stage_failure_keeps_official_data_and_resume_skips_success(self):
        calls = []
        def execute(command):
            name = Path(command[1]).name
            calls.append(name)
            if name == "funding_table.py" and calls.count(name) == 1:
                return 1
            return 0
        with patch.object(runner, "validate_candidates"):
            self.assertEqual(runner.run(self.root, "2026-09-07", ["feed", "funding"], execute=execute), 1)
            self.assertEqual((self.root / "data/manus/sentinel.txt").read_text(), "old")
            self.assertEqual(runner.run(self.root, "2026-09-07", ["feed", "funding"], execute=execute, resume=True), 0)
        self.assertEqual(calls, ["build_manus_feed.py", "funding_table.py", "funding_table.py"])
        self.assertFalse((self.root / "work/pipeline.lock").exists())

    def test_no_promote_retains_candidate_and_official_data(self):
        runner.run(self.root, "2026-09-07", ["snapshot"], execute=lambda c: 0, no_promote=True)
        self.assertEqual((self.root / "web/public/sentinel.txt").read_text(), "old")
        latest = json.loads((self.root / "work/runs/2026-09-07/latest.json").read_text())
        self.assertTrue((self.root / "work/runs/2026-09-07" / latest["runId"] / "workspace/web/public").exists())

    def test_resume_rejects_changed_configuration(self):
        runner.run(self.root, "2026-09-07", ["feed"], execute=lambda c: 1)
        with (self.root / "config/taxonomy.json").open("a") as f:
            f.write(" ")
        with self.assertRaisesRegex(ValueError, "配置"):
            runner.run(self.root, "2026-09-07", ["feed"], resume=True, execute=lambda c: 0)

    def test_resume_cannot_overwrite_newer_official_data(self):
        runner.run(self.root, "2026-09-07", ["feed"], execute=lambda c: 0, no_promote=True)
        (self.root / "data/manus/sentinel.txt").write_text("newer")
        with patch.object(runner, "validate_candidates"), self.assertRaisesRegex(ValueError, "正式数据"):
            runner.run(self.root, "2026-09-07", ["feed"], resume=True, execute=lambda c: 0)
        self.assertEqual((self.root / "data/manus/sentinel.txt").read_text(), "newer")

    def test_publication_failure_restores_previous_directories(self):
        run_dir = self.root / "work/test-run"
        for rel in ("data/manus", "web/public"):
            candidate = run_dir / "workspace" / rel
            candidate.mkdir(parents=True)
            (candidate / "sentinel.txt").write_text("new")
        replace = os.replace
        failed = False
        def interrupt(source, destination):
            nonlocal failed
            if Path(source) == run_dir / "workspace/web/public" and not failed:
                failed = True
                raise OSError("simulated disk failure")
            return replace(source, destination)
        with patch.object(publish.os, "replace", side_effect=interrupt), self.assertRaises(OSError):
            publish.publish(self.root, run_dir, ["data/manus", "web/public"])
        for rel in ("data/manus", "web/public"):
            self.assertEqual((self.root / rel / "sentinel.txt").read_text(), "old")
        self.assertEqual(json.loads((run_dir / "publication.json").read_text())["status"], "rolled_back")

    def test_recover_pending_publication_after_interruption(self):
        run_dir = self.root / "work/interrupted"
        candidate = run_dir / "workspace/data/manus"
        backup = run_dir / "backup/data/manus"
        candidate.mkdir(parents=True)
        backup.parent.mkdir(parents=True)
        (candidate / "sentinel.txt").write_text("new")
        publish.save(run_dir / "publication.json", {"status": "pending", "entries": [
            {"path": "data/manus", "existed": True}]})
        os.replace(self.root / "data/manus", backup)
        os.replace(candidate, self.root / "data/manus")
        publish.recover(self.root, run_dir)
        self.assertEqual((self.root / "data/manus/sentinel.txt").read_text(), "old")
        self.assertEqual((candidate / "sentinel.txt").read_text(), "new")

    def test_existing_lock_blocks_another_run(self):
        (self.root / "work").mkdir()
        (self.root / "work/pipeline.lock").write_text("locked")
        with self.assertRaises(FileExistsError):
            runner.run(self.root, "2026-09-07", ["feed"], execute=lambda c: 0)
        self.assertTrue((self.root / "work/pipeline.lock").exists())

    def test_discovery_resume_reuses_valid_successful_group(self):
        from types import SimpleNamespace
        from manus_source import runner as discovery
        cached = json.loads((ROOT / "tests/fixtures/manus/discovery-group-a.json").read_text(encoding="utf-8"))
        cached["articles"] = []
        for audit in cached["source_audits"]:
            audit.update(source_status="complete", article_count=0, note="当天无文章")
        raw = self.root / "work/manus/2026-08-16/raw"
        raw.mkdir(parents=True)
        (raw / "discovery-group_a.json").write_text(json.dumps(cached), encoding="utf-8")
        settings = SimpleNamespace(manus_api_key="mock", manus_agent_profile="manus-1.6", poll_seconds=10,
            timeout_seconds=3600, register_grace_seconds=90, work_dir=self.root / "work/manus",
            sources_path=ROOT / "config/manus_sources.json", discovery_prompt_path=ROOT / "scripts/prompts/manus_discovery.md")
        with patch.object(discovery.Settings, "from_environment", return_value=settings), \
             patch.object(discovery, "ManusClient") as client:
            self.assertEqual(discovery.main(["--date", "2026-08-16", "--groups", "group_a", "--resume"]), 0)
        client.return_value.create_crawl_task.assert_not_called()

    def test_preflight_reports_names_without_secret_values(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sensitive-test-value"}, clear=True):
            checks = doctor.inspect(self.root, ["feed"])
        self.assertNotIn("sensitive-test-value", json.dumps(checks))
        self.assertTrue(next(c for c in checks if c["check"] == "DEEPSEEK_API_KEY")["ok"])
        with patch.dict(os.environ, {}, clear=True):
            checks = doctor.inspect(self.root, ["feed"])
        self.assertFalse(next(c for c in checks if c["check"] == "DEEPSEEK_API_KEY")["ok"])

    def test_dry_run_is_read_only_and_never_executes(self):
        with patch.object(run_pipeline, "ROOT", self.root), patch.object(run_pipeline, "run") as run_mock:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(run_pipeline.main(["run", "--dry-run", "--date", "2026-09-07"]), 0)
        run_mock.assert_not_called()
        self.assertFalse((self.root / "work").exists())
        self.assertEqual([s["stage"] for s in json.loads(out.getvalue())["stages"]], list(runner.STAGES))

    def test_invalid_candidate_is_not_published(self):
        with self.assertRaises((FileNotFoundError, ValueError)):
            runner.run(self.root, "2026-09-07", ["funding"], execute=lambda c: 0)
        self.assertEqual((self.root / "web/public/sentinel.txt").read_text(), "old")

    def test_fixture_full_run_publishes_feed_snapshot_and_funding_together(self):
        import build_snapshot
        import tag_news
        from datetime import datetime
        date = "2026-08-16"
        raw = self.root / "work/manus" / date / "raw"
        raw.mkdir(parents=True)
        fixtures = ROOT / "tests/fixtures/manus"
        def execute(command):
            script = Path(command[1]).name
            if script == "runner.py":
                for g in "abc":
                    shutil.copyfile(fixtures / f"discovery-group-{g}.json", raw / f"discovery-group_{g}.json")
            elif script == "content_phase.py":
                shutil.copyfile(fixtures / "content-batch.json", raw / "content-batch-01.json")
            elif script == "build_manus_feed.py":
                output = Path(command[command.index("--data-dir") + 1])
                def enrich(items, tx, cache_path):
                    return {enrich_news.enrich_item_key(i): {"enrichmentStatus": "complete",
                        "summary": "离线测试摘要。" * 20,
                        "classification": {"category": "general", "tags": {}, "autoFallback": False,
                                           "autoFilled": []}} for i in items}
                feed = build_manus_feed.build(date, self.root / "work/manus", self.root / "config/manus_sources.json",
                                             self.root / "config/taxonomy.json", enrich_fn=enrich,
                                             cache_path=output / "enrichment_cache.json")
                build_manus_feed.promote_feed(feed, output, self.root / "config/taxonomy.json")
            elif script == "build_snapshot.py":
                item = {"id": "mock-live", "title": "模拟实时资讯", "source": "AIHOT", "category": "industry",
                        "url": "https://example.com/news", "publishedAt": datetime.now(build_snapshot.BJ).isoformat()}
                with patch.object(sys, "argv", command[1:] + ["--no-tags", "--manus-max-stale-days", "100000", "--archive-days", "100000"]), \
                     patch.object(build_snapshot, "fetch_items", return_value=[item]), \
                     patch.object(build_snapshot, "fetch_hot_topics", return_value={"topics": []}):
                    return build_snapshot.main()
            elif script == "funding_table.py":
                def arg(name): return Path(command[command.index(name) + 1])
                table = funding_table.build_funding_table(arg("--snapshot"), arg("--feed"), self.root / "work/manus",
                                                         TX, arg("--cache-dir"), skip_search=True)
                funding_table.promote_table(table, arg("--data-dir"), arg("--public-dir"))
            elif script == "build_company_overview.py":
                def arg(name): return Path(command[command.index(name) + 1])
                data = build_company_overview.build(
                    arg("--snapshot"), arg("--feed"), self.root / "work/manus",
                    arg("--previous"), arg("--cache-dir"), TX,
                    llm_fn=lambda *a, **k: '{"companies": []}',
                    generated_at="2026-08-16T10:05:00+08:00")
                build_company_overview.promote(data, arg("--data-dir"), arg("--public-dir"))
            return 0
        # snapshot 模板仍读实际仓库，所有输出由计划显式指向临时候选目录。
        old_taxonomy = build_snapshot.TAG_TAXONOMY
        try:
            self.assertEqual(runner.run(self.root, date, list(runner.STAGES), execute=execute, skip_search=True), 0)
        finally:
            build_snapshot.TAG_TAXONOMY = old_taxonomy
        self.assertTrue((self.root / "web/public/snapshot.json").is_file())
        self.assertTrue((self.root / "web/public/history/2026-08-16.html").is_file())
        feed = json.loads((self.root / "data/manus/current.json").read_text(encoding="utf-8"))
        self.assertEqual(len(feed["items"]), 9)
        self.assertEqual(json.loads((self.root / "web/public/funding-table.json").read_text(encoding="utf-8"))["companies"], [])
        self.assertEqual(json.loads((self.root / "web/public/company-overview.json").read_text(encoding="utf-8"))["companies"], [])


if __name__ == "__main__":
    unittest.main()
