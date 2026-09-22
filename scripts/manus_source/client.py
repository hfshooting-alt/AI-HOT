"""client.py — Manus API v2 客户端（纯标准库）。

相对仓库外层原型（ai news url crawler_20260810）的增强：
  - 任务创建：有限指数退避 + 抖动，仅对 429/5xx/连接中断重试
  - 轮询：task.listMessages 支持 cursor 分页，不固定只看前 200 条
  - 请求速率限制：可配置最小请求间隔，避免突破账户限额
  - transport 可注入：离线单测用伪造响应覆盖全部分支
"""
from __future__ import annotations

import base64
import json
import math
import random
import time
import threading
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API_BASE_URL = "https://api.manus.ai/v2"

RETRYABLE_HTTP_MARKERS = ("Manus HTTP 429", "Manus HTTP 500", "Manus HTTP 502",
                          "Manus HTTP 503", "Manus HTTP 504", "Cannot reach Manus API")

# Manus 会把等待内部并行子任务返回标记为 waiting/cascadeJobCall。这个状态不需要
# 用户输入，也不是终态；继续轮询即可。其他 waiting 类型仍按阻塞处理。
INTERNAL_WAIT_EVENT_TYPES = {"cascadeJobCall"}

# 发现阶段 structured output schema（v2：source_audits 区分“无文章”与“来源失败”）
DISCOVERY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_group": {"type": "string"},
        "target_date": {"type": "string"},
        "source_audits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "account_name": {"type": "string"},
                    "source_status": {"type": "string", "enum": ["complete", "partial", "failed"]},
                    "article_count": {"type": "integer"},
                    "note": {"type": ["string", "null"]},
                },
                "required": ["account_name", "source_status", "article_count", "note"],
                "additionalProperties": False,
            },
        },
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "account_name": {"type": ["string", "null"]},
                    "source_platform": {"type": ["string", "null"]},
                    "source_home_url": {"type": ["string", "null"]},
                    "article_url": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "published_date": {"type": ["string", "null"]},
                    "author": {"type": ["string", "null"]},
                    "extraction_status": {"type": "string", "enum": ["complete", "failed"]},
                    "note": {"type": ["string", "null"]},
                },
                "required": ["account_name", "source_platform", "source_home_url", "article_url",
                             "title", "published_date", "author", "extraction_status", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["source_group", "target_date", "source_audits", "articles"],
    "additionalProperties": False,
}


class ManusAPIError(RuntimeError):
    def __init__(self, message, *, reason_code=None, creation_state=None):
        super().__init__(message)
        self.reason_code = reason_code
        self.creation_state = creation_state


def credit_creation_rejection(data, http_status=None):
    """Only the observed, explicit platform rejection proves no task was made."""
    if http_status not in (None, 429) or not isinstance(data, dict):
        return False
    error = data.get('error')
    return (data.get('ok') is False and data.get('task_id') in (None, '')
            and isinstance(error, dict) and error.get('code') == 'resource_exhausted'
            and isinstance(error.get('message'), str)
            and error['message'].strip().lower() == 'credit limit exceeded')


def credit_rejection_error():
    return ManusAPIError('account_credits_exhausted: platform rejected creation; task not created',
                         reason_code='account_credits_exhausted', creation_state='not_created')


def observed_at() -> str:
    """Client observation time, never a substitute for a remote event timestamp."""
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='milliseconds')


def remote_time(value, *, milliseconds=False):
    try:
        if isinstance(value, bool) or value is None:
            return None
        return datetime.fromtimestamp(float(value) / (1000 if milliseconds else 1),
                                      ZoneInfo('Asia/Shanghai')).isoformat(timespec='milliseconds')
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def validate_output_schema(schema: dict, path: str = '$') -> None:
    """提交前检查 Manus 的对象字段约束，避免将格式错误发到付费接口。"""
    if not isinstance(schema, dict):
        return
    if 'properties' in schema:
        if set(schema['properties']) != set(schema.get('required', [])):
            raise ValueError(f'{path}: all output properties must be required')
        if schema.get('additionalProperties') is not False:
            raise ValueError(f'{path}: additionalProperties must be false')
        for name, child in schema['properties'].items():
            validate_output_schema(child, f'{path}.{name}')
    if isinstance(schema.get('items'), dict):
        validate_output_schema(schema['items'], f'{path}[]')
    for keyword in ('anyOf', 'oneOf', 'allOf'):
        for child in schema.get(keyword, []):
            validate_output_schema(child, path)


@dataclass(frozen=True)
class CreatedTask:
    task_id: str
    task_url: str


def default_transport(method: str, path: str, payload: dict[str, Any] | None,
                      api_key: str) -> dict[str, Any]:
    """真实 HTTP transport；返回已解析 JSON。网络/HTTP 错误统一包成 ManusAPIError。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        url=f"{API_BASE_URL}/{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "x-manus-api-key": api_key},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        try:
            rejected = credit_creation_rejection(json.loads(details), error.code)
        except (ValueError, TypeError):
            rejected = False
        if method == 'POST' and path == 'task.create' and rejected:
            raise credit_rejection_error() from error
        raise ManusAPIError(f"Manus HTTP {error.code}: {details}") from error
    except URLError as error:
        raise ManusAPIError(f"Cannot reach Manus API: {error.reason}") from error


class ManusClient:
    def __init__(
        self,
        api_key: str,
        agent_profile: str,
        poll_seconds: float,
        timeout_seconds: float,
        transport: Callable[[str, str, dict | None], dict] | None = None,
        register_grace_seconds: float = 90,
        create_retries: int = 3,
        retry_base_seconds: float = 2.0,
        retry_jitter_seconds: float = 1.0,
        min_request_interval_seconds: float = 0.0,
        page_limit: int = 200,
        create_interval_seconds: float = 0.0,
        inline_prompt: bool = False,
        diagnostics_dir=None,
        late_result_grace_seconds: float = 0,
        require_terminal_confirmation: bool = False,
        credit_usage_grace_seconds: float = 90,
    ) -> None:
        self.api_key = api_key
        self.inline_prompt = inline_prompt
        self.diagnostics_dir = diagnostics_dir
        self.late_result_grace_seconds = min(15, max(0, late_result_grace_seconds))
        self.require_terminal_confirmation = require_terminal_confirmation
        if (type(credit_usage_grace_seconds) not in (int, float)
                or not math.isfinite(credit_usage_grace_seconds) or credit_usage_grace_seconds < 0):
            raise ValueError('Credit usage grace must be finite and non-negative')
        self.credit_usage_grace_seconds = credit_usage_grace_seconds
        self.last_credit_balance = {'total': None, 'refresh': None, 'usable': None,
                                    'profile': agent_profile, 'complete': False}
        self.agent_profile = agent_profile
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.transport = transport or (lambda m, p, pl: default_transport(m, p, pl, api_key))
        self.register_grace_seconds = register_grace_seconds
        self.create_retries = create_retries
        self.retry_base_seconds = retry_base_seconds
        self.retry_jitter_seconds = retry_jitter_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self.page_limit = page_limit
        self._last_request_at = 0.0
        self.create_interval_seconds = create_interval_seconds
        self._create_lock = threading.Lock()
        self._next_create_at = 0.0
        self._creation_blocked = threading.Event()
        self._creation_block_reason = None
        self._creation_block_lock = threading.Lock()
        self._task_statuses: dict[str, str] = {}
        self._task_receipts: dict[str, dict] = {}
        self._receipt_callbacks = {}
        self._receipt_lock = threading.RLock()
        self._receipt_context = threading.local()

    @contextmanager
    def receipt_scope(self, callback):
        """Bind one worker's source without sharing its identity with other threads."""
        previous = getattr(self._receipt_context, 'callback', None)
        self._receipt_context.callback = callback
        try:
            yield
        finally:
            self._receipt_context.callback = previous

    @staticmethod
    def _emit_receipt(callback, receipt):
        if callback:
            try:
                callback(deepcopy(receipt))
            except Exception as error:  # Receipt observers must never retry or orphan a paid task.
                # A failed audit write must not lose an already-created task ID.
                print(f'Manus receipt persistence failed: {type(error).__name__}', flush=True)

    def task_receipt(self, task_id):
        with self._receipt_lock:
            return deepcopy(self._task_receipts.get(task_id, {}))

    def _update_receipt(self, task_id, **fields):
        with self._receipt_lock:
            receipt = self._task_receipts.setdefault(task_id, {'taskId': task_id})
            receipt.update(fields)
            snapshot = deepcopy(receipt)
            callback = self._receipt_callbacks.get(task_id)
        self._emit_receipt(callback, snapshot)

    def _observe_status(self, task_id, status, event_at=None, source='task.listMessages'):
        if status not in ('pending', 'running', 'waiting', 'stopped', 'error'):
            return
        receipt = self.task_receipt(task_id)
        previous_event = receipt.get('lastStatusEventAt')
        if event_at and previous_event and event_at < previous_event:
            return  # Re-reading an earlier page must not regress a known terminal state.
        now = observed_at()
        fields = {'lastRemoteStatus': status, 'lastStatusObservedAt': now,
                  'lastStatusSource': source, 'terminalConfirmed': status in ('stopped', 'error')}
        if event_at:
            fields['lastStatusEventAt'] = event_at
        if fields['terminalConfirmed']:
            fields['terminalObservedAt'] = receipt.get('terminalObservedAt') or now
            if event_at:
                fields['terminalEventAt'] = event_at
        self._task_statuses[task_id] = status
        self._update_receipt(task_id, **fields)

    def _observe_messages(self, task_id, response):
        # Inspect the whole page, including a terminal event after structured output.
        for event in response.get('messages', []):
            if self.require_terminal_confirmation and event.get('type') == 'error_message':
                if self._is_credit_exhausted(event.get('error_message', {}).get('content')):
                    # Inspect the whole page even when a result precedes the error.
                    self.block_new_tasks('account_credits_exhausted')
            if event.get('type') == 'status_update':
                self._observe_status(task_id, event.get('status_update', {}).get('agent_status'),
                                     remote_time(event.get('timestamp'), milliseconds=True))

    def _observe_detail(self, task_id, response):
        task = response.get('task')
        if not isinstance(task, dict):
            return
        fields = {}
        for key, field in (('created_at', 'remoteCreatedAt'), ('updated_at', 'remoteUpdatedAt')):
            value = remote_time(task.get(key))
            if value:
                fields[field] = value
        credits = task.get('credit_usage')
        if type(credits) in (int, float) and credits >= 0 and (type(credits) is int or math.isfinite(credits)):
            fields.update(lastObservedCredits=credits, creditsObservedAt=observed_at(),
                          creditsObservedWithTerminalStatus=task.get('status') in ('stopped', 'error'))
        if fields:
            self._update_receipt(task_id, **fields)
        self._observe_status(task_id, task.get('status'), source='task.detail')

    # ================= 基础请求 =================

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None,
                 *, before_create=None) -> dict[str, Any]:
        if method == 'POST' and path == 'task.create':
            # 三个采集线程共用客户端；创建节奏与任务执行并发分别控制。
            with self._create_lock:
                if self._creation_blocked.is_set():
                    raise self.creation_blocked_error()
                wait = self._next_create_at - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                if self._creation_blocked.is_set():
                    raise self.creation_blocked_error()
                self._next_create_at = time.monotonic() + self.create_interval_seconds
                try:
                    if before_create:
                        before_create()
                    response = self._send_request(method, path, payload)
                    if self.require_terminal_confirmation and self.create_retries == 0:
                        task_id = response.get('task_id')
                        if not isinstance(task_id, str) or not task_id.strip():
                            raise ManusAPIError('Task create response has no usable task ID')
                    return response
                except Exception as error:
                    if getattr(error, 'reason_code', None) == 'account_credits_exhausted':
                        self.block_new_tasks('account_credits_exhausted')
                    elif self.require_terminal_confirmation and self.create_retries == 0:
                        # Keep the create lock until queued workers see the circuit.
                        # A lost response can still represent a running paid task.
                        self.block_new_tasks('creation_unknown')
                    if isinstance(error, ManusAPIError) and self.create_interval_seconds > 0 and any(
                            code in str(error) for code in ('HTTP 429', 'rate_limited', 'resource_exhausted')):
                        self._next_create_at = max(self._next_create_at, time.monotonic() + 60)
                    raise
        return self._send_request(method, path, payload)

    def _send_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.min_request_interval_seconds > 0:
            wait = self._last_request_at + self.min_request_interval_seconds - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        data = self.transport(method, path, payload)
        self._last_request_at = time.monotonic()
        if not data.get("ok"):
            if method == 'POST' and path == 'task.create' and credit_creation_rejection(data):
                raise credit_rejection_error()
            error = data.get("error", {})
            raise ManusAPIError(f"Manus error {error.get('code')}: {error.get('message')}")
        return data

    def available_credits(self) -> int:
        """Return profile-usable credits; daily refresh credits only fund Lite.

        A legacy total-only response is allowed outside production, explicitly
        marked complete=False. Production requires the complete balance split.
        """
        self.last_credit_balance = {'total': None, 'refresh': None, 'usable': None,
                                    'profile': self.agent_profile, 'complete': False}
        response = self._request("GET", "usage.availableCredits")
        balance = response
        if balance.get('total_credits') is None and isinstance(response.get('data'), dict):
            balance = response['data']
        total = balance.get('total_credits')
        if type(total) is not int or total < 0:
            raise ManusAPIError("Manus balance unavailable")
        self.last_credit_balance['total'] = total
        if 'refresh_credits' not in balance:
            if self.require_terminal_confirmation:
                raise ManusAPIError('Manus balance unavailable: refresh credits missing')
            self.last_credit_balance['usable'] = total
            return total
        refresh = balance['refresh_credits']
        if type(refresh) is not int or not 0 <= refresh <= total:
            raise ManusAPIError('Manus balance unavailable: invalid refresh credits')
        usable = total if self.agent_profile == 'manus-1.6-lite' else total - refresh
        self.last_credit_balance.update(refresh=refresh, usable=usable, complete=True)
        return usable

    def stop_task(self, task_id: str) -> None:
        """Request stopping; an accepted request alone does not confirm termination."""
        self._update_receipt(task_id, stopRequestedObservedAt=observed_at(), stopAccepted=False)
        self._request("POST", "task.stop", {"task_id": task_id})
        self._update_receipt(task_id, stopAccepted=True, stopAcceptedObservedAt=observed_at())

    def block_new_tasks(self, reason='remote_stop_unconfirmed') -> None:
        """Block queued creations before a worker can start its next source."""
        if reason not in ('remote_stop_unconfirmed', 'creation_unknown', 'account_credits_exhausted'):
            reason = 'remote_stop_unconfirmed'
        with self._creation_block_lock:
            if not self._creation_blocked.is_set():
                self._creation_block_reason = reason
            self._creation_blocked.set()

    def creation_blocked_error(self):
        with self._creation_block_lock:
            reason = self._creation_block_reason or 'remote_stop_unconfirmed'
        return ManusAPIError(f'cost_circuit_open: {reason}; task not created',
                             reason_code=reason, creation_state='not_created')

    def confirm_task_stopped(self, task_id: str, max_attempts: int = 3) -> dict:
        """Reuse drained status messages, otherwise make at most three detail reads."""
        status = self._task_statuses.get(task_id)
        error = None
        for attempt in range(min(3, max(1, max_attempts))):
            if status in ('stopped', 'error'):
                return {'confirmed': True, 'remoteStatus': status, 'error': None}
            if attempt:
                time.sleep(min(30, max(5, self.poll_seconds)))
            try:
                detail = self._request('GET', 'task.detail?' + urlencode({'task_id': task_id}))
                self._observe_detail(task_id, detail)
                task = detail.get('task')
                status = task.get('status') if isinstance(task, dict) else None
                status = status if isinstance(status, str) else None
                if isinstance(status, str):
                    self._task_statuses[task_id] = status
                error = None
            except (OSError, ValueError, ManusAPIError) as exc:
                error = str(exc)[:160]
        confirmed = status in ('stopped', 'error')
        return {'confirmed': confirmed, 'remoteStatus': status or 'unknown',
                'error': None if confirmed else (error or 'Remote stop not confirmed; task may still consume credits')}

    @staticmethod
    def _is_retryable(error_text: str) -> bool:
        return any(marker in error_text for marker in RETRYABLE_HTTP_MARKERS)

    @staticmethod
    def _is_credit_exhausted(error_text) -> bool:
        if not isinstance(error_text, str):
            return False
        text = error_text.lower().replace('_', ' ').replace('-', ' ')
        return any(marker in text for marker in (
            'not enough credit', 'insufficient credit', 'credit balance is insufficient',
            'credit balance insufficient', 'credits exhausted', 'credits are exhausted'))

    # ================= 任务创建（指数退避 + 抖动） =================

    @staticmethod
    def build_task_content(prompt_text: str, source_group: str, target_date: str,
                           task_brief: str) -> list[dict[str, str]]:
        """完整 prompt 以 Manus 文件附件下发；可见消息只带本次调度参数。"""
        encoded_prompt = base64.b64encode(prompt_text.encode("utf-8")).decode("ascii")
        return [
            {
                "type": "text",
                "text": (
                    f"请先完整阅读附件中的 prompt 文件，并严格遵守其中全部规则。\n\n"
                    "# 本次任务要求\n"
                    f"source_group：{source_group}\n"
                    f"target_date：{target_date}\n"
                    "时区：Asia/Shanghai\n\n"
                    f"{task_brief}"
                ),
            },
            {
                "type": "file",
                "file_data": f"data:text/markdown;charset=utf-8;base64,{encoded_prompt}",
                "filename": "manus_task_prompt.md",
                "mime_type": "text/markdown",
            },
        ]

    def create_crawl_task(self, prompt_text: str, source_group: str, target_date: str,
                          title: str, task_brief: str,
                          output_schema: dict | None = None) -> CreatedTask:
        schema = output_schema or DISCOVERY_OUTPUT_SCHEMA
        validate_output_schema(schema)
        payload = {
            "message": {"content": self.build_task_content(prompt_text, source_group,
                                                           target_date, task_brief)},
            "interactive_mode": False,
            "hide_in_task_list": True,
            "title": title,
            "agent_profile": self.agent_profile,
            "structured_output_schema": schema,
        }
        if self.inline_prompt:
            payload['message']['content'] = [{'type': 'text', 'text':
                f'source_group: {source_group}\ntarget_date: {target_date}\n'
                f'{task_brief}\n\n{prompt_text}'}]
        if self.diagnostics_dir:
            from manus_source.diagnostics import record_task_request
            record_task_request(self.diagnostics_dir, payload)
        last_error: ManusAPIError | None = None
        callback = getattr(self._receipt_context, 'callback', None)
        receipt = {'taskId': None, 'creationState': 'not_created', 'createAttempts': 0,
                   'createRequestedObservedAt': None, 'createdResponseObservedAt': None,
                   'lastRemoteStatus': 'unknown', 'terminalConfirmed': False,
                   'terminalObservedAt': None, 'terminalEventAt': None}

        def before_create():
            receipt.update(creationState='unknown', createAttempts=receipt['createAttempts'] + 1,
                           createRequestedObservedAt=observed_at())
            self._emit_receipt(callback, receipt)

        for attempt in range(self.create_retries + 1):
            try:
                response = self._request("POST", "task.create", payload, before_create=before_create)
                task_id = response['task_id']
                if not isinstance(task_id, str) or not task_id.strip():
                    raise ManusAPIError('Task create response has no usable task ID')
                if self.diagnostics_dir:
                    record_task_request(self.diagnostics_dir, payload, task_id=task_id)
                receipt.update(taskId=task_id, creationState='created',
                               createdResponseObservedAt=observed_at())
                with self._receipt_lock:
                    self._task_receipts[task_id] = deepcopy(receipt)
                    self._receipt_callbacks[task_id] = callback
                self._emit_receipt(callback, receipt)
                task_url = response.get('task_url')
                if not isinstance(task_url, str) or not task_url.strip():
                    task_url = 'https://manus.im/app/' + quote(task_id, safe='')
                return CreatedTask(task_id=task_id, task_url=task_url)
            except Exception as error:
                if not isinstance(error, ManusAPIError):
                    receipt['creationState'] = 'unknown' if receipt['createAttempts'] else 'not_created'
                    self._emit_receipt(callback, receipt)
                    raise
                last_error = error
                if error.creation_state == 'not_created':
                    if attempt > 0:
                        # A later explicit refusal cannot disprove a task from
                        # an earlier lost response in the legacy retry path.
                        receipt.update(creationState='unknown', notCreatedReason=None)
                        self._emit_receipt(callback, receipt)
                        raise ManusAPIError(f'{error.reason_code}: rejected or blocked after an earlier unknown creation',
                                             reason_code=error.reason_code, creation_state='unknown') from error
                    receipt.update(creationState='not_created', notCreatedReason=error.reason_code)
                    self._emit_receipt(callback, receipt)
                    raise
                if attempt >= self.create_retries or not self._is_retryable(str(error)):
                    receipt['creationState'] = 'unknown' if receipt['createAttempts'] else 'not_created'
                    self._emit_receipt(callback, receipt)
                    raise
                delay = self.retry_base_seconds * (2 ** attempt)
                delay += random.uniform(0, self.retry_jitter_seconds)
                print(f"[create] 瞬时错误（{error}），{delay:.1f}s 后重试 "
                      f"{attempt + 1}/{self.create_retries}", flush=True)
                time.sleep(delay)
        raise last_error  # pragma: no cover - 循环内必然 return 或 raise

    # ================= 轮询（cursor 分页） =================

    def _process_page(self, response: dict, last_status: str | None,
                      last_error: str | None) -> tuple[dict | None, str | None, str | None]:
        """处理一页消息：返回 (structured value 或 None, 最新状态, 最新错误文本)。

        任务级终态（error/waiting）直接抛 ManusAPIError。
        """
        for event in response.get("messages", []):
            status_update = event.get("status_update", {}) if event.get("type") == "status_update" else {}
            agent_status = status_update.get("agent_status")
            if agent_status and agent_status != last_status:
                last_status = agent_status
            event_type = event.get("type")
            if event_type == "structured_output_result":
                result = event.get("structured_output_result", {})
                if result.get("success"):
                    value = result.get("value")
                    if isinstance(value, dict):
                        return value, last_status, last_error
                last_error = result.get("error") or "Structured output extraction failed"
            elif event_type == "error_message":
                last_error = event.get("error_message", {}).get("content") or "Task error"
                if self.require_terminal_confirmation and self._is_credit_exhausted(last_error):
                    self.block_new_tasks('account_credits_exhausted')
                    raise ManusAPIError('Manus credits exhausted')
            elif event_type == "status_update":
                if agent_status == "error":
                    raise ManusAPIError(last_error or "Task failed")
                if agent_status == "waiting":
                    detail = status_update.get("status_detail", {})
                    waiting_for = detail.get("waiting_for_event_type")
                    if waiting_for not in INTERNAL_WAIT_EVENT_TYPES:
                        raise ManusAPIError(f"Task is waiting for {waiting_for}")
        return None, last_status, last_error

    def wait_for_structured_result(self, task_id: str,
                                   observed_credit_limit: int | None = None, on_checkpoint=None) -> dict[str, Any]:
        """轮询直到拿到 structured output；注册延迟/瞬时错误继续轮询，终态与超时抛异常。"""
        deadline = time.monotonic() + self.timeout_seconds
        credit_seen_at = deadline - self.timeout_seconds
        watch_credits = self.require_terminal_confirmation and observed_credit_limit is not None
        availability_deadline = time.monotonic() + self.register_grace_seconds
        last_error: str | None = None
        last_status: str | None = None
        stopped_since: float | None = None

        def require_recent_credit_observation():
            if watch_credits and time.monotonic() - credit_seen_at >= self.credit_usage_grace_seconds:
                raise ManusAPIError('Manus credit usage unavailable beyond observation grace')

        while time.monotonic() < deadline:
            try:
                cursor: str | None = None
                seen_cursors = set()
                for _ in range(10):
                    query = {"task_id": task_id, "order": "asc", "limit": str(self.page_limit)}
                    if cursor:
                        query["cursor"] = cursor
                    response = self._request("GET", f"task.listMessages?{urlencode(query)}")
                    self._observe_messages(task_id, response)
                    if on_checkpoint:
                        from .checkpoints import checkpoint_articles
                        for article in checkpoint_articles(response):
                            on_checkpoint(article)
                    value, last_status, last_error = self._process_page(response, last_status, last_error)
                    if last_status and task_id not in self._task_statuses:
                        self._task_statuses[task_id] = last_status
                    if value is not None:
                        return value
                    cursor = response.get("next_cursor")
                    if not cursor:
                        break
                    if cursor in seen_cursors:
                        raise ManusAPIError('Repeated Manus message cursor')
                    seen_cursors.add(cursor)
                # A stopped task may deliver its structured result on a later
                # page/poll. Drain pages first, allow a short delivery grace,
                # then let the caller recover checkpoints instead of waiting an hour.
                if last_status == "stopped":
                    if stopped_since is None:
                        stopped_since = time.monotonic()
                    elif time.monotonic() - stopped_since >= 30:
                        raise ManusAPIError("Task stopped without structured result: " +
                                            (last_error or "no result delivered"))
                else:
                    stopped_since = None
                if observed_credit_limit is not None:
                    detail = self._request("GET", "task.detail?" + urlencode({"task_id": task_id}))
                    self._observe_detail(task_id, detail)
                    task_detail = detail.get('task')
                    credits = task_detail.get('credit_usage') if isinstance(task_detail, dict) else None
                    valid_credits = type(credits) in (int, float) and credits >= 0 and (
                        type(credits) is int or math.isfinite(credits))
                    if valid_credits and watch_credits:
                        credit_seen_at = time.monotonic()
                    elif not valid_credits:
                        require_recent_credit_observation()
                    if valid_credits and credits >= observed_credit_limit:
                        raise ManusAPIError(
                            f"Observed credit threshold reached: {credits} >= {observed_credit_limit}")
                if last_status:
                    print(f"[{task_id}] Manus status: {last_status}", flush=True)
            except ManusAPIError as error:
                error_text = str(error)
                if self.require_terminal_confirmation and self._is_credit_exhausted(error_text):
                    self.block_new_tasks('account_credits_exhausted')
                    raise
                require_recent_credit_observation()
                # task.create 返回的 task_id 可能短暂查不到：注册延迟，不算失败
                if "Manus HTTP 404" in error_text and time.monotonic() < availability_deadline:
                    print(f"[{task_id}] Manus task is registering; retrying…", flush=True)
                    time.sleep(self.poll_seconds)
                    continue
                # 远端任务可能活得过瞬时断连/限流/5xx：继续轮询直到总超时
                if self._is_retryable(error_text):
                    last_error = error_text
                    print(f"[{task_id}] Manus polling connection interrupted; retrying…", flush=True)
                    time.sleep(self.poll_seconds)
                    continue
                raise
            time.sleep(self.poll_seconds)
        raise TimeoutError(last_error or f"Timed out waiting for Manus task {task_id}")

    def read_stopped_results(self, task_id, on_checkpoint):
        """One bounded, read-only sweep after stop; no task creation or continuation."""
        from .checkpoints import checkpoint_articles
        cursor = None
        result = None
        for _ in range(10):
            query = {'task_id': task_id, 'order': 'asc', 'limit': str(self.page_limit)}
            if cursor:
                query['cursor'] = cursor
            response = self._request('GET', 'task.listMessages?' + urlencode(query))
            self._observe_messages(task_id, response)
            for article in checkpoint_articles(response):
                on_checkpoint(article)
            for event in response.get('messages', []):
                structured = event.get('structured_output_result', {})
                if event.get('type') == 'structured_output_result' and structured.get('success'):
                    value = structured.get('value')
                    if isinstance(value, dict):
                        result = value
            cursor = response.get('next_cursor')
            if not cursor:
                break
        return result
