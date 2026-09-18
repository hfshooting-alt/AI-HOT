#!/usr/bin/env python3
"""test_manus_client.py — ManusClient 离线单测（伪造 HTTP transport，不发真实请求）。

覆盖：创建成功/重试退避/不可重试错误、注册延迟 404、轮询瞬时 5xx、
cursor 分页、waiting/error 终态、整体超时、结构化输出失败计数。

运行：python -m unittest tests.test_manus_client -v
"""
import os
import sys
import unittest
from unittest.mock import patch, Mock
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from manus_source.client import ManusAPIError, ManusClient, validate_output_schema  # noqa: E402


class FakeTransport:
    """按脚本顺序返回响应；脚本耗尽后重复最后一项（供超时类测试使用）。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if len(self.script) > 1:
            item = self.script.pop(0)
        else:
            item = self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def make_client(script, **kw):
    defaults = dict(poll_seconds=0, timeout_seconds=5, register_grace_seconds=60,
                    create_retries=2, retry_base_seconds=0, retry_jitter_seconds=0)
    defaults.update(kw)
    transport = FakeTransport(script)
    client = ManusClient(api_key="fake-key", agent_profile="manus-1.6",
                         transport=transport, **defaults)
    return client, transport


OK_CREATE = {"ok": True, "task_id": "t-1", "task_url": "https://manus.app/task/t-1"}


def page(messages, next_cursor=None):
    d = {"ok": True, "messages": messages}
    if next_cursor:
        d["next_cursor"] = next_cursor
    return d


def structured_ok(value):
    return {"type": "structured_output_result",
            "structured_output_result": {"success": True, "value": value}}


RESULT_VALUE = {"source_group": "group_a", "target_date": "2026-08-16",
                "source_audits": [], "articles": []}


class StoppedTaskTests(unittest.TestCase):
    def test_stopped_without_result_exits_after_delivery_grace(self):
        clock = [0]
        client, transport = make_client([page([{'type': 'status_update',
            'status_update': {'agent_status': 'stopped'}}])],
            poll_seconds=10, timeout_seconds=3600)
        with patch('manus_source.client.time.monotonic', side_effect=lambda: clock[0]), \
             patch('manus_source.client.time.sleep', side_effect=lambda n: clock.__setitem__(0, clock[0]+n)):
            with self.assertRaisesRegex(ManusAPIError, 'Task stopped without structured result'):
                client.wait_for_structured_result('stopped-task')
        self.assertEqual(clock[0], 30)
        self.assertEqual(len(transport.calls), 4)

    def test_stopped_drains_next_page_before_ending(self):
        client, transport = make_client([
            page([{'type': 'status_update', 'status_update': {'agent_status': 'stopped'}}], 'next'),
            page([structured_ok(RESULT_VALUE)])])
        self.assertEqual(client.wait_for_structured_result('task'), RESULT_VALUE)
        self.assertIn('cursor=next', transport.calls[1][1])

    def test_stopped_accepts_delayed_result_on_next_poll(self):
        client, _ = make_client([
            page([{'type': 'status_update', 'status_update': {'agent_status': 'stopped'}}]),
            page([structured_ok(RESULT_VALUE)])])
        self.assertEqual(client.wait_for_structured_result('task'), RESULT_VALUE)


class TestCreateTask(unittest.TestCase):
    def test_window_schema_passes_strict_validation_before_creation(self):
        from manus_source.runner import run_discovery
        from manus_source.window import ten_am_window
        client = Mock()
        def capture(**kwargs):
            validate_output_schema(kwargs['output_schema'])
            self.assertIn('published_time_text', kwargs['output_schema']['properties']['articles']['items']['required'])
            raise RuntimeError('validated-without-creating')
        client.create_crawl_task.side_effect = capture
        with self.assertRaisesRegex(RuntimeError, 'validated-without-creating'):
            run_discovery(client, 'group_a', '2026-09-16', 'test', ['Test'], ten_am_window('2026-09-16'))

    def test_invalid_schema_never_reaches_transport(self):
        client, transport = make_client([])
        with self.assertRaisesRegex(ValueError, 'all output properties'):
            client.create_crawl_task('p','g','d','t','b', {'type':'object', 'properties':{'time':{'type':['string','null']}}, 'required':[], 'additionalProperties':False})
        self.assertEqual(transport.calls, [])

    def test_concurrent_failed_creates_are_spaced_and_429_cools_queue(self):
        now = [100.0]
        stamps = []
        def transport(method, path, payload):
            stamps.append(now[0])
            raise ManusAPIError('Manus HTTP 429' if len(stamps) == 2 else 'Manus HTTP 400')
        client = ManusClient('fake', 'manus-1.6', 0, 1, transport=transport,
                             create_retries=0, create_interval_seconds=7)
        def attempt(_):
            with self.assertRaises(ManusAPIError):
                client.create_crawl_task('p','g','d','t','b')
        with patch('manus_source.client.time.monotonic', side_effect=lambda: now[0]), \
             patch('manus_source.client.time.sleep', side_effect=lambda seconds: now.__setitem__(0, now[0]+seconds)):
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(attempt, range(20)))
        self.assertEqual(len(stamps), 20)  # 无创建重试，全部队列均获得机会。
        self.assertEqual(stamps[:3], [100, 107, 167])
        self.assertTrue(all(b-a >= 7 for a,b in zip(stamps,stamps[1:])))

    def test_balance_and_stop_helpers(self):
        client, transport = make_client([
            {"ok": True, "total_credits": 42},
            {"ok": True},
        ])
        self.assertEqual(client.available_credits(), 42)
        client.stop_task("t-1")
        self.assertEqual(transport.calls[1], ("POST", "task.stop", {"task_id": "t-1"}))

    def test_balance_supports_legacy_nested_shape(self):
        client, _ = make_client([{"ok": True, "data": {"total_credits": 41}}])
        self.assertEqual(client.available_credits(), 41)

    def test_invalid_balance_is_rejected(self):
        client, _ = make_client([{"ok": True, "total_credits": None}])
        with self.assertRaisesRegex(ManusAPIError, "balance unavailable"):
            client.available_credits()

    def test_create_success_payload_shape(self):
        client, transport = make_client([OK_CREATE])
        task = client.create_crawl_task("PROMPT 正文", "group_a", "2026-08-16",
                                        title="标题", task_brief="简报")
        self.assertEqual(task.task_id, "t-1")
        method, path, payload = transport.calls[0]
        self.assertEqual((method, path), ("POST", "task.create"))
        self.assertFalse(payload["interactive_mode"])
        self.assertIn("structured_output_schema", payload)
        parts = payload["message"]["content"]
        self.assertEqual(parts[0]["type"], "text")
        self.assertIn("group_a", parts[0]["text"])
        self.assertEqual(parts[1]["type"], "file")  # prompt 以附件下发
        self.assertTrue(parts[1]["file_data"].startswith("data:text/markdown"))

    def test_create_retries_on_rate_limit_then_succeeds(self):
        client, transport = make_client([
            ManusAPIError("Manus HTTP 429: rate limited"),
            ManusAPIError("Cannot reach Manus API: connection reset"),
            OK_CREATE,
        ])
        task = client.create_crawl_task("P", "group_a", "2026-08-16", "t", "b")
        self.assertEqual(task.task_id, "t-1")
        self.assertEqual(len(transport.calls), 3)

    def test_create_non_retryable_raises_immediately(self):
        client, transport = make_client([ManusAPIError("Manus HTTP 400: bad request"), OK_CREATE])
        with self.assertRaises(ManusAPIError):
            client.create_crawl_task("P", "group_a", "2026-08-16", "t", "b")
        self.assertEqual(len(transport.calls), 1)

    def test_create_retries_exhausted_raises(self):
        client, transport = make_client([ManusAPIError("Manus HTTP 503: unavailable")],
                                        create_retries=2)
        with self.assertRaises(ManusAPIError):
            client.create_crawl_task("P", "group_a", "2026-08-16", "t", "b")
        self.assertEqual(len(transport.calls), 3)  # 1 次 + 2 次重试

    def test_business_error_envelope_raises(self):
        client, _ = make_client([{"ok": False, "error": {"code": "quota", "message": "no quota"}}])
        with self.assertRaises(ManusAPIError) as ctx:
            client.create_crawl_task("P", "group_a", "2026-08-16", "t", "b")
        self.assertIn("quota", str(ctx.exception))


class TestWaitForResult(unittest.TestCase):
    def test_observed_credit_limit_reads_messages_before_stop(self):
        client, transport = make_client([
            {"ok": True, "task": {"status": "running", "credit_usage": 20}},
        ])
        with self.assertRaisesRegex(ManusAPIError, "Observed credit threshold"):
            client.wait_for_structured_result("t-1", observed_credit_limit=20)
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(transport.calls[0][1].startswith("task.listMessages?"))
        self.assertTrue(transport.calls[1][1].startswith("task.detail?"))

    def test_immediate_structured_result(self):
        client, _ = make_client([page([structured_ok(RESULT_VALUE)])])
        self.assertEqual(client.wait_for_structured_result("t-1"), RESULT_VALUE)

    def test_registration_delay_404_then_success(self):
        client, transport = make_client([
            ManusAPIError("Manus HTTP 404: task not found"),
            page([structured_ok(RESULT_VALUE)]),
        ])
        self.assertEqual(client.wait_for_structured_result("t-1"), RESULT_VALUE)
        self.assertEqual(len(transport.calls), 2)

    def test_404_after_grace_period_raises(self):
        client, _ = make_client([ManusAPIError("Manus HTTP 404: task not found")],
                                register_grace_seconds=0, timeout_seconds=1)
        with self.assertRaises(ManusAPIError):
            client.wait_for_structured_result("t-1")

    def test_retryable_5xx_during_polling_continues(self):
        client, transport = make_client([
            ManusAPIError("Manus HTTP 502: bad gateway"),
            page([structured_ok(RESULT_VALUE)]),
        ])
        self.assertEqual(client.wait_for_structured_result("t-1"), RESULT_VALUE)
        self.assertEqual(len(transport.calls), 2)

    def test_pagination_follows_cursor(self):
        client, transport = make_client([
            page([{"type": "status_update", "status_update": {"agent_status": "running"}}],
                 next_cursor="c-2"),
            page([structured_ok(RESULT_VALUE)]),
        ])
        self.assertEqual(client.wait_for_structured_result("t-1"), RESULT_VALUE)
        self.assertEqual(len(transport.calls), 2)
        self.assertNotIn("cursor=", transport.calls[0][1])
        self.assertIn("cursor=c-2", transport.calls[1][1])

    def test_waiting_status_raises(self):
        client, _ = make_client([page([{
            "type": "status_update",
            "status_update": {"agent_status": "waiting",
                              "status_detail": {"waiting_for_event_type": "user_input"}},
        }])])
        with self.assertRaises(ManusAPIError) as ctx:
            client.wait_for_structured_result("t-1")
        self.assertIn("waiting", str(ctx.exception))

    def test_internal_cascade_wait_continues_polling(self):
        client, transport = make_client([
            page([{
                "type": "status_update",
                "status_update": {"agent_status": "waiting",
                                  "status_detail": {"waiting_for_event_type": "cascadeJobCall"}},
            }]),
            page([structured_ok(RESULT_VALUE)]),
        ])
        self.assertEqual(client.wait_for_structured_result("t-1"), RESULT_VALUE)
        self.assertEqual(len(transport.calls), 2)

    def test_error_status_raises_with_last_error(self):
        client, _ = make_client([page([
            {"type": "error_message", "error_message": {"content": "浏览器会话崩溃"}},
            {"type": "status_update", "status_update": {"agent_status": "error"}},
        ])])
        with self.assertRaises(ManusAPIError) as ctx:
            client.wait_for_structured_result("t-1")
        self.assertIn("浏览器会话崩溃", str(ctx.exception))

    def test_failed_structured_extraction_then_success(self):
        client, _ = make_client([
            page([{"type": "structured_output_result",
                   "structured_output_result": {"success": False, "error": "schema mismatch"}}],
                 next_cursor="c-2"),
            page([structured_ok(RESULT_VALUE)]),
        ])
        self.assertEqual(client.wait_for_structured_result("t-1"), RESULT_VALUE)

    def test_overall_timeout(self):
        client, _ = make_client(
            [page([{"type": "status_update", "status_update": {"agent_status": "running"}}])],
            timeout_seconds=0.02, poll_seconds=0.01)
        with self.assertRaises(TimeoutError):
            client.wait_for_structured_result("t-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
