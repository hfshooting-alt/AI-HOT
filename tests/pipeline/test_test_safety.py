"""测试成本保护：所有 Manus 响应均模拟，无真实任务。"""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from _tempdir import make_temp_dir
from testing.offline import OfflineViolation, isolated
from testing.manus_probe import ProbeError, auth, smoke, MAX_POLLS, balance
from testing.llm_probe import LLMProbeError, smoke as llm_smoke


class TestCostSafety(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_temp_dir("test-cost-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.calls = []

    def send(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == "usage.availableCredits":
            return {"ok": True, "data": {"total_credits": 100}}
        if path == "task.create":
            self.assertEqual(payload["agent_profile"], "lite")
            self.assertEqual(payload["share_visibility"], "private")
            return {"ok": True, "task_id": "fake-test-task"}
        if path.startswith("task.detail?"):
            return {"ok": True, "task": {"status": "stopped", "credit_usage": 2}}
        if path.startswith("task.listMessages?"):
            return {"ok": True, "messages": [{"type": "structured_output_result",
                "structured_output_result": {"success": True, "value": {"ok": True}}}]}
        if path == "task.stop":
            return {"ok": True}
        self.fail("unexpected endpoint")

    def run_smoke(self, **kwargs):
        return smoke(self.root, "fake-key", allow_paid=True, send=kwargs.pop("send", self.send),
                     today=kwargs.pop("today", "2026-09-09"), clock=lambda: 0, sleep=lambda _: None, **kwargs)

    def test_offline_rejects_network_and_processes_even_when_caught(self):
        with isolated() as violations:
            for action in (lambda: socket.create_connection(("example.com", 443)),
                           lambda: subprocess.run(["curl", "https://example.com"])):
                with self.assertRaises(OfflineViolation):
                    action()
            self.assertEqual(len(violations), 2)

    def test_auth_is_single_read_and_cache_is_key_specific(self):
        first = auth(self.root, "fake-key", send=self.send, now=100)
        self.assertTrue(first["ok"])
        cached = auth(self.root, "fake-key", send=self.send, now=200)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["requestsThisRun"], 0)
        auth(self.root, "new-fake-key", send=self.send, now=200)
        self.assertEqual([c[:2] for c in self.calls], [("GET", "usage.availableCredits")] * 2)

    def test_auth_failure_does_not_retry_and_caches_failure(self):
        def failed(*args):
            self.calls.append(args)
            raise ProbeError("HTTP_401")
        result = auth(self.root, "fake-key", send=failed, now=100)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "HTTP_401")
        auth(self.root, "fake-key", send=failed, now=101)
        self.assertEqual(len(self.calls), 1)

    def test_smoke_requires_opt_in_before_any_request(self):
        with self.assertRaisesRegex(ProbeError, "paid_opt_in_required"):
            smoke(self.root, "fake-key", send=self.send)
        self.assertFalse(self.calls)

    def test_success_records_usage_and_blocks_second_task_today(self):
        result = self.run_smoke()
        self.assertTrue(result["ok"])
        self.assertEqual(result["taskCredits"], 2)
        self.assertTrue(result["resolved"])
        with self.assertRaisesRegex(ProbeError, "daily_task_attempt_limit"):
            self.run_smoke()
        self.assertEqual(sum(c[1] == "task.create" for c in self.calls), 1)

    def test_create_timeout_never_retries_and_blocks_next_day(self):
        def uncertain(method, path, payload=None):
            if path == "task.create":
                self.calls.append((method, path, payload))
                raise ProbeError("connection_failed")
            return self.send(method, path, payload)
        result = self.run_smoke(send=uncertain)
        self.assertFalse(result["resolved"])
        self.assertEqual(result["createAttempts"], 1)
        with self.assertRaisesRegex(ProbeError, "unresolved_previous_task"):
            self.run_smoke(today="2026-09-10")
        self.assertEqual(sum(c[1] == "task.create" for c in self.calls), 1)

    def test_poll_limit_requests_stop_and_never_creates_again(self):
        def running(method, path, payload=None):
            if path.startswith("task.detail?"):
                self.calls.append((method, path, payload))
                return {"ok": True, "task": {"status": "running"}}
            return self.send(method, path, payload)
        result = self.run_smoke(send=running)
        self.assertFalse(result["ok"])
        self.assertTrue(result["stopRequested"])
        self.assertTrue(result["resolved"])
        self.assertEqual(sum(c[1].startswith("task.detail?") for c in self.calls), MAX_POLLS)
        self.assertEqual(sum(c[1] == "task.stop" for c in self.calls), 1)
        self.assertLessEqual(result["requests"], 18)

    def test_credit_threshold_stops_early_and_stop_failure_stays_unresolved(self):
        def expensive(method, path, payload=None):
            if path.startswith("task.detail?"):
                return {"ok": True, "task": {"status": "running", "credit_usage": 20}}
            if path == "task.stop":
                raise ProbeError("connection_failed")
            return self.send(method, path, payload)
        result = self.run_smoke(send=expensive)
        self.assertEqual(result["error"], "observed_credit_threshold")
        self.assertFalse(result["resolved"])
        self.assertEqual(result["stopError"], "connection_failed")

    def test_auth_or_low_balance_prevents_task_creation(self):
        self.assertEqual(balance({"ok": True, "total_credits": 4350}), 4350)
        self.assertEqual(balance({"ok": True, "data": {"total_credits": 100}}), 100)
        for data in ([], {}, {"total_credits": None}, {"total_credits": True}, {"total_credits": -1}):
            with self.assertRaisesRegex(ProbeError, "balance_unavailable"):
                balance({"data": data})
        def low(*args):
            self.calls.append(args)
            return {"ok": True, "data": {"total_credits": 1}}
        with self.assertRaisesRegex(ProbeError, "insufficient_test_reserve"):
            self.run_smoke(send=low)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(list((self.root / "work/test-cost").glob("smoke-*.json")))

    def test_running_lock_blocks_a_second_probe(self):
        folder = self.root / "work/test-cost"
        folder.mkdir(parents=True)
        (folder / "probe.lock").touch()
        with self.assertRaisesRegex(ProbeError, "probe_locked"):
            auth(self.root, "fake-key", send=self.send)
        self.assertFalse(self.calls)

    def test_llm_smoke_is_one_tiny_daily_json_request(self):
        tx = {"model": {"api_key_env": "DEEPSEEK_API_KEY", "api_base_env": "LLM_API_BASE",
                        "default_base": "https://example.com", "model": "test-model"}}
        sent = []
        def send(payload):
            sent.append(payload)
            return {"choices": [{"message": {"content": '{"ok":true}'}}],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14,
                              "ignored": "value"}}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}, clear=True):
            result = llm_smoke(self.root, tx, allow_paid=True, send=send,
                               today="2026-09-09", now=100)
            self.assertTrue(result["ok"])
            self.assertEqual(result["usage"], {"prompt_tokens": 9, "completion_tokens": 5,
                                               "total_tokens": 14})
            self.assertEqual(sent[0]["max_tokens"], 16)
            self.assertEqual(len(sent), 1)
            with self.assertRaisesRegex(LLMProbeError, "daily_llm_attempt_limit"):
                llm_smoke(self.root, tx, allow_paid=True, send=send,
                          today="2026-09-09", now=101)
        self.assertEqual(len(sent), 1)

    def test_llm_smoke_disables_v4_thinking_and_records_failed_usage(self):
        tx = {"model": {"api_key_env": "DEEPSEEK_API_KEY", "api_base_env": "LLM_API_BASE",
                        "default_base": "https://example.com", "model": "deepseek-v4-flash"}}
        sent = []
        def send(payload):
            sent.append(payload)
            return {"choices": [{"message": {"content": ""}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 16, "total_tokens": 28}}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}, clear=True):
            result = llm_smoke(self.root, tx, allow_paid=True, send=send,
                               today="2026-09-11", now=100)
        self.assertEqual(sent[0]["thinking"], {"type": "disabled"})
        self.assertEqual(result["error"], "structured_result_invalid")
        self.assertEqual(result["usage"]["total_tokens"], 28)

    def test_llm_smoke_requires_opt_in_and_valid_json(self):
        tx = {"model": {"api_key_env": "DEEPSEEK_API_KEY", "api_base_env": "LLM_API_BASE",
                        "default_base": "https://example.com", "model": "test-model"}}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}, clear=True):
            with self.assertRaisesRegex(LLMProbeError, "paid_opt_in_required"):
                llm_smoke(self.root, tx, send=lambda _: {})
            result = llm_smoke(self.root, tx, allow_paid=True,
                               send=lambda _: {"choices": [{"message": {"content": "no"}}]},
                               today="2026-09-10", now=100)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "structured_result_invalid")


if __name__ == "__main__":
    unittest.main()
