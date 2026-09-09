"""固定范围的 Manus 探针；不支持采集 prompt、附件或生产数据发布。"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from automation.publish import save

BASE = "https://api.manus.ai/v2/"
MAX_POLLS = 12
OBSERVE_SECONDS = 120
STOP_AT_CREDITS = 20  # 轮询看到的消费阈值，不是服务端硬性账单上限。


class ProbeError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(key, method, path, payload=None):
    """单次请求，10 秒 socket 超时，不自动重试，不跟随重定向。"""
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(BASE + path, data=body, method=method,
                  headers={"Content-Type": "application/json", "x-manus-api-key": key})
    try:
        with build_opener(NoRedirect).open(req, timeout=10) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise ProbeError(f"HTTP_{exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise ProbeError("connection_failed") from None
    except ValueError:
        raise ProbeError("invalid_response") from None
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise ProbeError("api_rejected")
    return data


def balance(response):
    # API v2 当前把 total_credits 放在顶层；兼容早期 data.total_credits 响应。
    value = response.get("total_credits")
    if value is None:
        data = response.get("data")
        value = data.get("total_credits") if isinstance(data, dict) else None
    if type(value) is not int or value < 0:
        raise ProbeError("balance_unavailable")
    return value


@contextmanager
def locked(root):
    folder = root / "work/test-cost"
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "probe.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ProbeError("probe_locked") from None
    os.close(fd)
    try:
        yield folder
    finally:
        lock.unlink()


def auth(root, key, *, refresh=False, send=None, now=None):
    """单个只读余额请求即可验证认证；按密钥缓存，显示检查时间。"""
    send = send or (lambda method, path, payload=None: request(key, method, path, payload))
    now = time.time() if now is None else now
    signature = hashlib.sha256(key.encode()).hexdigest()
    with locked(root) as folder:
        path = folder / "auth.json"
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            ttl = 86400 if prev["ok"] else 3600
            if not refresh and prev["keyFingerprint"] == signature and 0 <= now - prev["checkedAt"] < ttl:
                return {**prev, "cached": True, "requestsThisRun": 0}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result = {"checkedAt": now, "keyFingerprint": signature,
                  "requestsThisRun": 1, "createdTasks": 0, "cached": False}
        try:
            result.update(ok=True, availableCredits=balance(send("GET", "usage.availableCredits")))
        except ProbeError as exc:
            result.update(ok=False, error=exc.code)
        save(path, result)
        return result


def smoke(root, key, *, allow_paid=False, send=None, today=None, clock=None, sleep=None):
    """单个 lite 固定问答。每天最多预留一次创建尝试，创建不重试。"""
    if not allow_paid:
        raise ProbeError("paid_opt_in_required")
    send = send or (lambda method, path, payload=None: request(key, method, path, payload))
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    with locked(root) as folder:
        path = folder / f"smoke-{today}.json"
        if path.exists():
            raise ProbeError("daily_task_attempt_limit")
        for old in folder.glob("smoke-*.json"):
            if not json.loads(old.read_text(encoding="utf-8")).get("resolved"):
                raise ProbeError("unresolved_previous_task")
        state = {"date": today, "ok": False, "resolved": False, "createAttempts": 0,
                 "requests": 0, "taskCredits": None, "stopRequested": False}

        def call(method, endpoint, payload=None):
            state["requests"] += 1
            save(path, state)
            return send(method, endpoint, payload)

        # 鉴权或余额失败不创建任务，也不占用当天付费名额。
        before = balance(send("GET", "usage.availableCredits"))
        if before < STOP_AT_CREDITS:
            raise ProbeError("insufficient_test_reserve")
        state.update(balanceBefore=before, requests=1, createAttempts=1)
        save(path, state)  # 发出创建前占位：断连后也不能盲目重建。
        task_id = None
        terminal = False
        deadline = clock() + OBSERVE_SECONDS
        try:
            created = call("POST", "task.create", {
                "agent_profile": "lite", "interactive_mode": False,
                "share_visibility": "private", "title": "AI HOT minimal API check",
                "message": {"content": [{"type": "text", "text":
                    "Reply OK only, then finish. Do not browse, search, create files, use connectors or run code."}],
                    "connectors": []},
                "structured_output_schema": {"type": "object", "properties": {
                    "ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
            })
            task_id = created.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise ProbeError("creation_result_unknown")
            state["taskId"] = task_id
            save(path, state)
            for _ in range(MAX_POLLS):
                if clock() >= deadline:
                    break
                task = call("GET", "task.detail?" + urlencode({"task_id": task_id})).get("task") or {}
                credits = task.get("credit_usage")
                if type(credits) in (int, float):
                    state["taskCredits"] = credits
                status = task.get("status")
                if status in ("stopped", "error"):
                    terminal = True
                    state["resolved"] = True
                    if status == "error":
                        raise ProbeError("task_failed")
                    messages = call("GET", "task.listMessages?" + urlencode({
                        "task_id": task_id, "order": "desc", "limit": 20}))
                    state["ok"] = any(
                        e.get("type") == "structured_output_result"
                        and (e.get("structured_output_result") or {}).get("success") is True
                        and (e.get("structured_output_result") or {}).get("value") == {"ok": True}
                        for e in messages.get("messages", []))
                    if not state["ok"]:
                        state["error"] = "structured_result_missing"
                    break
                if status == "waiting":
                    raise ProbeError("task_waiting")
                if state["taskCredits"] is not None and state["taskCredits"] >= STOP_AT_CREDITS:
                    raise ProbeError("observed_credit_threshold")
                sleep(min(10, max(0, deadline - clock())))
            else:
                state["error"] = "poll_limit"
            if not terminal and "error" not in state:
                state["error"] = "observation_timeout"
        except ProbeError as exc:
            state["error"] = exc.code
        finally:
            if task_id and not terminal:
                state["stopRequested"] = True
                try:
                    call("POST", "task.stop", {"task_id": task_id})
                    state["resolved"] = True
                except ProbeError as exc:
                    state["stopError"] = exc.code
            try:
                state["balanceAfter"] = balance(call("GET", "usage.availableCredits"))
            except ProbeError as exc:
                state["balanceError"] = exc.code
            save(path, state)
        return state
