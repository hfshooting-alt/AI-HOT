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
