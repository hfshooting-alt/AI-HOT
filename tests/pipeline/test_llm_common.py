#!/usr/bin/env python3
"""test_llm_common.py — llm_common 的 .env 加载与 LLM_MODEL 解析离线单测（不发真实请求）。

运行：python -m unittest tests.test_llm_common -v
"""
import os
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
from _tempdir import make_temp_dir  # noqa: E402
import llm_common  # noqa: E402

ENV_KEYS = ("DEEPSEEK_API_KEY", "LLM_MODEL", "LLM_API_BASE")


class TestLoadDotenv(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir("llm-common-test-")
        # 隔离环境：前置测试可能已把项目根 .env 载入 os.environ，导致
        # setdefault 语义下的 BOM 断言失败（与 tearDown 对称清理）
        for key in ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key in ENV_KEYS:
            os.environ.pop(key, None)

    def test_loads_keys_from_env_file(self):
        Path(self.tmp, ".env").write_text(
            "DEEPSEEK_API_KEY=sk-test-123\nLLM_MODEL=my-model\n", encoding="utf-8")
        llm_common.load_dotenv(Path(self.tmp, ".env"))
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "sk-test-123")
        self.assertEqual(os.environ["LLM_MODEL"], "my-model")

    def test_existing_env_wins(self):
        os.environ["DEEPSEEK_API_KEY"] = "already-set"
        Path(self.tmp, ".env").write_text("DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")
        llm_common.load_dotenv(Path(self.tmp, ".env"))
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "already-set")

    def test_missing_file_is_noop(self):
        llm_common.load_dotenv(Path(self.tmp, "nope.env"))  # 不抛异常

    def test_comments_and_blank_lines_ignored(self):
        Path(self.tmp, ".env").write_text("# comment\n\nFOO=bar\n", encoding="utf-8")
        llm_common.load_dotenv(Path(self.tmp, ".env"))
        self.assertEqual(os.environ.get("FOO"), "bar")

    def test_quoted_value_keeps_raw_text(self):
        # 与 manus_source.config.load_dotenv 语义一致：不做引号剥离
        Path(self.tmp, ".env").write_text('LLM_MODEL="quoted-model"\n', encoding="utf-8")
        llm_common.load_dotenv(Path(self.tmp, ".env"))
        self.assertEqual(os.environ["LLM_MODEL"], '"quoted-model"')

    def test_bom_first_line_not_dropped(self):
        # Windows 编辑器可能写出带 BOM 的 .env：首行 key 不得静默丢失
        Path(self.tmp, ".env").write_text(
            "DEEPSEEK_API_KEY=sk-bom-test\nLLM_MODEL=bom-model\n", encoding="utf-8-sig")
        llm_common.load_dotenv(Path(self.tmp, ".env"))
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "sk-bom-test")
        self.assertEqual(os.environ["LLM_MODEL"], "bom-model")


class TestResolveModel(unittest.TestCase):
    TX = {"model": {"model": "deepseek-chat"}}

    def tearDown(self):
        os.environ.pop("LLM_MODEL", None)

    def test_default_from_taxonomy(self):
        os.environ.pop("LLM_MODEL", None)
        self.assertEqual(llm_common.resolve_model(self.TX), "deepseek-chat")

    def test_env_override(self):
        os.environ["LLM_MODEL"] = "custom-model"
        self.assertEqual(llm_common.resolve_model(self.TX), "custom-model")

    def test_blank_env_falls_back(self):
        os.environ["LLM_MODEL"] = "   "
        self.assertEqual(llm_common.resolve_model(self.TX), "deepseek-chat")


class TestModelRequestOptions(unittest.TestCase):
    def test_deepseek_v4_disables_thinking(self):
        self.assertEqual(llm_common.model_request_options('DeepSeek-V4-Pro'),
                         {'thinking': {'type': 'disabled'}})
        self.assertEqual(llm_common.model_request_options("deepseek-v4-flash"),
                         {"thinking": {"type": "disabled"}})

    def test_other_openai_compatible_models_get_no_private_fields(self):
        self.assertEqual(llm_common.model_request_options("custom-model"), {})

    def test_production_call_has_output_cap_and_disables_v4_thinking(self):
        tx = {"model": {
            "api_key_env": "DEEPSEEK_API_KEY", "api_base_env": "LLM_API_BASE",
            "default_base": "https://example.com", "model": "deepseek-v4-flash",
            "temperature": 0, "max_output_tokens": 1024, "timeout_seconds": 20,
        }}
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return b'{"choices":[{"message":{"content":"{}"}}]}'
        def open_request(request, timeout):
            captured.update(body=json.loads(request.data), timeout=timeout)
            return Response()
        with patch.dict(os.environ, {
                "DEEPSEEK_API_KEY": "fake-key", "LLM_API_BASE": "https://example.com",
                "LLM_MODEL": "deepseek-v4-flash"}, clear=True), \
                patch.object(llm_common, "_DOTENV_LOADED", True), \
                patch.object(llm_common.urllib.request, "urlopen", side_effect=open_request):
            self.assertEqual(llm_common.call_llm(tx, "system", "user"), "{}")
        self.assertEqual(captured["body"]["max_tokens"], 1024)
        self.assertEqual(captured["body"]["thinking"], {"type": "disabled"})


class TestUsageLog(unittest.TestCase):
    def test_records_only_usage_metadata(self):
        target = Path(make_temp_dir("usage-log-test-"), "usage.jsonl")
        with patch.dict(os.environ, {"LLM_USAGE_LOG": str(target)}, clear=False):
            llm_common.record_usage("deepseek-v4-flash", {
                "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15,
                "untrusted_extra": "must-not-be-written"}, "relevance_screen")
        row = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(row["operation"], "relevance_screen")
        self.assertEqual(row["usage"]["total_tokens"], 15)
        self.assertNotIn("untrusted_extra", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
