import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tempdir import make_temp_dir  # noqa: E402
from manus_source import runner  # noqa: E402


class TestRunnerTimeout(unittest.TestCase):
    def test_runner_uses_one_hour_discovery_timeout(self):
        temp_path = Path(make_temp_dir("manus-runner-test-"))
        self.addCleanup(shutil.rmtree, temp_path, ignore_errors=True)
        sources_path = temp_path / "sources.json"
        prompt_path = temp_path / "prompt.md"
        sources_path.write_text(json.dumps({
            "groups": {
                "group_a": [{
                    "account_name": "TestAccount",
                    "platform": "Tencent News",
                    "home_url": "https://example.com",
                }],
            },
        }), encoding="utf-8")
        prompt_path.write_text("{{SOURCES}}", encoding="utf-8")

        settings = SimpleNamespace(
            manus_api_key="test-key",
            manus_agent_profile="manus-1.6",
            poll_seconds=10,
            timeout_seconds=3600,
            register_grace_seconds=300,
            sources_path=sources_path,
            discovery_prompt_path=prompt_path,
            work_dir=temp_path / "work",
        )
        captured = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        payload = {
            "articles": [],
            "source_audits": [{
                "account_name": "TestAccount",
                "source_status": "complete",
                "article_count": 0,
            }],
        }
        with patch.object(runner.Settings, "from_environment", return_value=settings), \
                patch.object(runner, "ManusClient", FakeClient), \
                patch.object(runner, "run_discovery", return_value=payload):
            exit_code = runner.main([
                "--date", "2026-08-27", "--groups", "group_a",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["timeout_seconds"], 3600)

    def test_failed_wait_requests_task_stop(self):
        stopped = []
        class FakeClient:
            def create_crawl_task(self, **kwargs):
                return SimpleNamespace(task_id="task-1", task_url="https://example.com/task-1")
            def wait_for_structured_result(self, task_id, observed_credit_limit=None):
                raise TimeoutError("timed out")
            def stop_task(self, task_id):
                stopped.append(task_id)
        with self.assertRaises(runner.DiscoveryRunError) as ctx:
            runner.run_discovery(FakeClient(), "group_a", "2026-08-27", "prompt", ["TestAccount"])
        self.assertEqual(stopped, ["task-1"])
        self.assertTrue(ctx.exception.stop_succeeded)
        self.assertEqual(ctx.exception.task_id, "task-1")


class TestSingleAccountCanary(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir("manus-canary-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.sources_path = self.root / "sources.json"
        self.prompt_path = self.root / "prompt.md"
        self.sources_path.write_text(json.dumps({"groups": {"group_a": [{
            "account_name": "TestAccount", "platform": "Tencent News",
            "home_url": "https://example.com/account",
        }]}}), encoding="utf-8")
        self.prompt_path.write_text("{{SOURCES}}", encoding="utf-8")
        self.settings = runner.Settings(
            manus_api_key="test-key", manus_agent_profile="manus-1.6", poll_seconds=10,
            timeout_seconds=3600, register_grace_seconds=90, content_batch_size=4,
            content_concurrency=2, content_mode="script", crawl_timeout_seconds=20,
            crawl_retries=2, crawl_concurrency=4, crawl_request_delay_seconds=1,
            crawl_user_agent=None, crawl_jina_fallback=False, max_content_chars=20000,
            min_content_chars=100, sources_path=self.sources_path,
            discovery_prompt_path=self.prompt_path, content_prompt_path=self.prompt_path,
            work_dir=self.root / "work",
        )

    def test_account_requires_paid_opt_in_before_loading_settings(self):
        with patch.object(runner.Settings, "from_environment") as load:
            with self.assertRaises(SystemExit):
                runner.main(["--account", "TestAccount"])
        load.assert_not_called()

    def test_account_canary_is_lite_single_attempt_and_isolated(self):
        captured = {}
        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)
            def available_credits(self):
                return 100 if "balance" not in captured else 98

        balances = iter((100, 98))
        FakeClient.available_credits = lambda self: next(balances)
        payload = {"articles": [], "source_audits": [{
            "account_name": "TestAccount", "source_status": "complete",
            "article_count": 0, "note": "当天无文章",
        }]}
        with patch.object(runner.Settings, "from_environment", return_value=self.settings), \
                patch.object(runner, "ManusClient", FakeClient), \
                patch.object(runner, "run_discovery", return_value=payload) as run:
            code = runner.main(["--date", "2026-09-10", "--account", "TestAccount",
                                "--allow-paid"])
        self.assertEqual(code, 0)
        self.assertEqual(captured["agent_profile"], "manus-1.6-lite")
        self.assertEqual(captured["create_retries"], 0)
        self.assertEqual(captured["poll_seconds"], 5)
        self.assertEqual(run.call_args.args[1], "group_a")
        self.assertEqual(run.call_args.args[4], ["TestAccount"])
        self.assertEqual(run.call_args.args[6], runner.CANARY_STOP_AT_CREDITS)
        base = self.settings.work_dir / "canary" / runner.canary_slug("TestAccount") / "2026-09-10"
        report = json.loads((base / "canary-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["creditsUsed"], 2)
        self.assertEqual(report["status"], "complete")
        self.assertTrue((base / "raw" / "discovery-group_a.json").exists())
        self.assertFalse((self.settings.work_dir / "2026-09-10").exists())

    def test_account_canary_accepts_bounded_credit_limit(self):
        captured = {}

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def available_credits(self):
                return 100

        payload = {"articles": [], "source_audits": [{
            "account_name": "TestAccount", "source_status": "complete",
            "article_count": 0, "note": "当天无文章",
        }]}
        with patch.object(runner.Settings, "from_environment", return_value=self.settings), \
                patch.object(runner, "ManusClient", FakeClient), \
                patch.object(runner, "run_discovery", return_value=payload) as run:
            code = runner.main(["--date", "2026-09-11", "--account", "TestAccount",
                                "--allow-paid", "--canary-credit-limit", "40"])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[6], 40)
        report_path = (self.settings.work_dir / "canary" / runner.canary_slug("TestAccount")
                       / "2026-09-11" / "canary-report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["creditLimit"], 40)

    def test_account_canary_rejects_unbounded_credit_limit(self):
        with patch.object(runner.Settings, "from_environment") as load:
            with self.assertRaises(SystemExit):
                runner.main(["--account", "TestAccount", "--allow-paid",
                             "--canary-credit-limit", "61"])
        load.assert_not_called()

    def test_production_credit_limit_is_bounded_and_disables_create_retry(self):
        captured = {}
        balances = iter((100, 95))

        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def available_credits(self):
                return next(balances)

        payload = {"articles": [], "source_audits": [{
            "account_name": "TestAccount", "source_status": "complete",
            "article_count": 0, "note": "当天无文章",
        }]}
        with patch.object(runner.Settings, "from_environment", return_value=self.settings), \
                patch.object(runner, "ManusClient", FakeClient), \
                patch.object(runner, "run_discovery", return_value=payload) as run:
            code = runner.main(["--date", "2026-09-12", "--groups", "group_a",
                                "--credit-limit-per-task", "60"])
        self.assertEqual(code, 0)
        self.assertEqual(captured["create_retries"], 0)
        self.assertEqual(run.call_args.args[6], 60)
        report = json.loads((self.settings.work_dir / "2026-09-12" / "cost-report.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(report["maxObservedRunCredits"], 60)
        self.assertEqual(report["creditsUsed"], 5)

    def test_account_name_must_be_unique(self):
        with self.assertRaisesRegex(ValueError, "不唯一"):
            runner.select_account({"group_a": [{"account_name": "same"}],
                                   "group_b": [{"account_name": "same"}]}, "same")

    def test_retry_failed_keeps_successful_source_cached(self):
        source = {"account_name": "TestAccount"}
        raw_dir = self.settings.work_dir / "2026-09-10" / "raw"
        account_dir = raw_dir / "accounts"
        account_dir.mkdir(parents=True)
        payload = runner.failed_source_payload("group_a", "2026-09-10", source, None, "test")
        payload["source_audits"][0].update(source_status="complete", note="当天无文章")
        (account_dir / f"{runner.canary_slug('TestAccount')}.json").write_text(
            json.dumps(payload), encoding="utf-8")
        cached, origin = runner.load_reusable_source_payload(
            raw_dir, self.settings.work_dir, "group_a", "2026-09-10", source,
            None, retry_failed=True)
        self.assertEqual(cached, payload)
        self.assertEqual(origin, "account-attempt")

    def test_failed_source_attempt_is_reused_without_paid_retry(self):
        source = {"account_name": "TestAccount", "platform": "Tencent News",
                  "home_url": "https://example.com"}
        window = runner.ten_am_window("2026-09-10")
        raw_dir = self.settings.work_dir / "ten-am" / "2026-09-10" / "raw"
        account_dir = raw_dir / "accounts"
        account_dir.mkdir(parents=True)
        payload = runner.failed_source_payload(
            "group_a", "2026-09-10", source, window, "credit threshold")
        (account_dir / f"{runner.canary_slug('TestAccount')}.json").write_text(
            json.dumps(payload), encoding="utf-8")

        cached, origin = runner.load_reusable_source_payload(
            raw_dir, self.settings.work_dir / "ten-am", "group_a", "2026-09-10",
            source, window)

        self.assertEqual(origin, "account-attempt")
        self.assertEqual(cached["source_audits"][0]["source_status"], "failed")
        retry, _ = runner.load_reusable_source_payload(
            raw_dir, self.settings.work_dir / "ten-am", "group_a", "2026-09-10",
            source, window, retry_failed=True)
        self.assertIsNone(retry)


class TestSettingsDefaults(unittest.TestCase):
    def test_settings_defaults_timeout_to_one_hour_without_env_override(self):
        temp_path = Path(make_temp_dir("manus-settings-test-"))
        self.addCleanup(shutil.rmtree, temp_path, ignore_errors=True)
        sources_path = temp_path / "config" / "manus_sources.json"
        sources_path.parent.mkdir()
        sources_path.write_text(json.dumps({
            "groups": {
                "group_a": [{
                    "account_name": "TestAccount",
                    "platform": "Tencent News",
                    "home_url": "https://example.com",
                }],
            },
        }), encoding="utf-8")
        prompt_dir = temp_path / "scripts" / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "manus_discovery.md").write_text("{{SOURCES}}", encoding="utf-8")

        with patch.dict(os.environ, {"MANUS_API_KEY": "isolated-test-key"}, clear=True):
            settings = runner.Settings.from_environment(temp_path)

        self.assertEqual(settings.timeout_seconds, 3600)


class TestDiscoveryPrompt(unittest.TestCase):
    def _render_prompt(self) -> str:
        prompt_path = Path(__file__).resolve().parents[2] / "scripts" / "prompts" / "manus_discovery.md"
        return runner.render_discovery_prompt(prompt_path, [{
            "account_name": "白鲸出海",
            "platform": "Official Baijing",
            "home_url": "https://www.baijing.cn/article/",
        }])

    def test_renders_source_config_and_preserves_identity_mapping(self):
        rendered = self._render_prompt()

        self.assertNotIn("{{SOURCES}}", rendered)
        self.assertIn("公众号名称：白鲸出海", rendered)
        self.assertIn("- url：https://www.baijing.cn/article/", rendered)
        self.assertIn("- 平台：Official Baijing", rendered)
        self.assertIn(
            "account_name、source_platform、source_home_url 必须从来源配置常量逐字复制",
            rendered,
        )
        self.assertIn("account_name = 当前来源配置的公众号名称", rendered)
        self.assertIn("source_platform = 当前来源配置的平台", rendered)
        self.assertIn("source_home_url = 当前来源配置的原始 url", rendered)
        self.assertIn(
            "正确：\n"
            "account_name = 白鲸出海\n"
            "source_platform = Official Baijing\n"
            "source_home_url = https://www.baijing.cn/article/\n"
            "错误：\n"
            "account_name = null\n"
            "source_platform = 白鲸出海\n"
            "source_home_url = https://www.baijing.cn/",
            rendered,
        )

    def test_requires_complete_article_field_integrity_check(self):
        rendered = self._render_prompt()

        self.assertIn(
            "每条 extraction_status=complete 的文章必须逐项检查字段完整性：account_name、source_platform、"
            "source_home_url、article_url、title、published_date、author、extraction_status、note 均必须存在；"
            "其中 author 与 note 可按本节规则使用 JSON null。",
            rendered,
        )
        for rule in (
            "account_name 非空，并且等于当前来源配置的公众号名称。",
            "source_platform 等于当前来源配置的平台。",
            "source_home_url 等于当前来源配置的原始 url。",
            "article_url 和 title 非空。",
            "published_date 等于 target_date。",
        ):
            self.assertIn(rule, rendered)
        self.assertIn("二次反查不一致时，按第三节第 4 小节仅排除该候选。", rendered)
        self.assertIn("来源级门槛失败时，来源按既有协议标记 failed。", rendered)

    def test_recounts_article_count_from_final_articles_by_account(self):
        rendered = self._render_prompt()

        self.assertIn(
            "article_count = 最终 articles 中 account_name 等于该账号且 extraction_status=complete 的记录数",
            rendered,
        )

    def test_requires_one_audit_per_configured_account_and_failed_audit_details(self):
        rendered = self._render_prompt()

        self.assertIn("每个配置账号恰好生成 1 条审计记录", rendered)
        self.assertIn("source_status=failed 时 article_count 必须为 0", rendered)
        self.assertIn("note 必须为非空失败说明", rendered)
        for rule in (
            "不得添加未配置账号。",
            "failed 来源不得保留 complete 文章。",
            "complete 且当天无文章时 article_count=0、note=“当天无文章”。",
        ):
            self.assertIn(rule, rendered)

    def test_requires_final_self_check_and_json_only_root_allowlist(self):
        rendered = self._render_prompt()

        self.assertIn("\n# 五、提交前强制自检\n", rendered)
        self.assertIn("\n# 六、最终回答\n", rendered)
        self.assertLess(rendered.index("\n# 五、提交前强制自检\n"), rendered.index("\n# 六、最终回答\n"))
        self.assertIn("根对象字段白名单为且仅为：source_group、target_date、source_audits、articles", rendered)
        self.assertIn("最终格式检查：只输出一个合法 JSON 对象", rendered)
        self.assertIn("每个对象只包含第四节和下方 JSON 示例规定的现有字段。", rendered)
        self.assertIn("禁止输出 Markdown、解释文字或代码围栏", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
