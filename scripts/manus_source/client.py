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
import random
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE_URL = "https://api.manus.ai/v2"

RETRYABLE_HTTP_MARKERS = ("Manus HTTP 429", "Manus HTTP 500", "Manus HTTP 502",
                          "Manus HTTP 503", "Manus HTTP 504", "Cannot reach Manus API")

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
                    "source_status": {"type": "string", "enum": ["complete", "failed"]},
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
    pass


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
    ) -> None:
        self.api_key = api_key
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

    # ================= 基础请求 =================

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.min_request_interval_seconds > 0:
            wait = self._last_request_at + self.min_request_interval_seconds - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        data = self.transport(method, path, payload)
        self._last_request_at = time.monotonic()
        if not data.get("ok"):
            error = data.get("error", {})
            raise ManusAPIError(f"Manus error {error.get('code')}: {error.get('message')}")
        return data

    def available_credits(self) -> int:
        """读取当前余额；兼容 Manus v2 新旧两种返回位置。"""
        response = self._request("GET", "usage.availableCredits")
        value = response.get("total_credits")
        if value is None and isinstance(response.get("data"), dict):
            value = response["data"].get("total_credits")
        if type(value) is not int or value < 0:
            raise ManusAPIError("Manus balance unavailable")
        return value

    def stop_task(self, task_id: str) -> None:
        """尽力停止已创建任务，供受限 canary 和超时收口使用。"""
        self._request("POST", "task.stop", {"task_id": task_id})

    @staticmethod
    def _is_retryable(error_text: str) -> bool:
        return any(marker in error_text for marker in RETRYABLE_HTTP_MARKERS)

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
        payload = {
            "message": {"content": self.build_task_content(prompt_text, source_group,
                                                           target_date, task_brief)},
            "interactive_mode": False,
            "hide_in_task_list": True,
            "title": title,
            "agent_profile": self.agent_profile,
            "structured_output_schema": output_schema or DISCOVERY_OUTPUT_SCHEMA,
        }
        last_error: ManusAPIError | None = None
        for attempt in range(self.create_retries + 1):
            try:
                response = self._request("POST", "task.create", payload)
                return CreatedTask(task_id=response["task_id"], task_url=response["task_url"])
            except ManusAPIError as error:
                last_error = error
                if attempt >= self.create_retries or not self._is_retryable(str(error)):
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
            elif event_type == "status_update":
                if agent_status == "error":
                    raise ManusAPIError(last_error or "Task failed")
                if agent_status == "waiting":
                    detail = status_update.get("status_detail", {})
                    raise ManusAPIError(f"Task is waiting for {detail.get('waiting_for_event_type')}")
        return None, last_status, last_error

    def wait_for_structured_result(self, task_id: str,
                                   observed_credit_limit: int | None = None) -> dict[str, Any]:
        """轮询直到拿到 structured output；注册延迟/瞬时错误继续轮询，终态与超时抛异常。"""
        deadline = time.monotonic() + self.timeout_seconds
        availability_deadline = time.monotonic() + self.register_grace_seconds
        last_error: str | None = None
        last_status: str | None = None
        while time.monotonic() < deadline:
            try:
                if observed_credit_limit is not None:
                    detail = self._request("GET", "task.detail?" + urlencode({"task_id": task_id}))
                    credits = (detail.get("task") or {}).get("credit_usage")
                    if type(credits) in (int, float) and credits >= observed_credit_limit:
                        raise ManusAPIError(
                            f"Observed credit threshold reached: {credits} >= {observed_credit_limit}")
                cursor: str | None = None
                while True:
                    query = {"task_id": task_id, "order": "asc", "limit": str(self.page_limit)}
                    if cursor:
                        query["cursor"] = cursor
                    response = self._request("GET", f"task.listMessages?{urlencode(query)}")
                    value, last_status, last_error = self._process_page(response, last_status, last_error)
                    if value is not None:
                        return value
                    cursor = response.get("next_cursor")
                    if not cursor:
                        break
                if last_status:
                    print(f"[{task_id}] Manus status: {last_status}", flush=True)
            except ManusAPIError as error:
                error_text = str(error)
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
