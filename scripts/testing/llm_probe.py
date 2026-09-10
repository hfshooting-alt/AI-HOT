"""单次极小 OpenAI-compatible JSON 请求；用于验证模型配置与结构化输出。"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from automation.publish import save
from llm_common import model_request_options, parse_output, resolve_model
from testing.manus_probe import locked


class LLMProbeError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def request(url: str, key: str, payload: dict) -> dict:
    """只发一次请求，10 秒超时，不重试。"""
    req = Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "AI-HOT/1.0 (+https://github.com/hfshooting-alt/AI-HOT)",
    })
    try:
        with urlopen(req, timeout=10) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise LLMProbeError(f"HTTP_{exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise LLMProbeError("connection_failed") from None
    except ValueError:
        raise LLMProbeError("invalid_response") from None
    if not isinstance(data, dict):
        raise LLMProbeError("invalid_response")
    return data


def _safe_usage(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    allowed = ("prompt_tokens", "completion_tokens", "total_tokens")
    result = {key: value[key] for key in allowed if type(value.get(key)) is int and value[key] >= 0}
    return result or None


def smoke(root: Path, tx: dict, *, allow_paid=False, send=None, today=None, now=None) -> dict:
    """每天最多一次 16-token JSON 请求；结果只记录状态和 token 数。"""
    if not allow_paid:
        raise LLMProbeError("paid_opt_in_required")
    model_cfg = tx["model"]
    key = os.getenv(model_cfg["api_key_env"], "").strip()
    if not key or key.lower().startswith("your-"):
        raise LLMProbeError("missing_api_key")
    base = (os.getenv(model_cfg["api_base_env"], "").strip() or model_cfg["default_base"]).rstrip("/")
    model = resolve_model(tx)
    endpoint = base + "/chat/completions"
    send = send or (lambda payload: request(endpoint, key, payload))
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    checked_at = time.time() if now is None else now
    signature = hashlib.sha256(f"{key}\0{base}\0{model}".encode()).hexdigest()
    with locked(root) as folder:
        path = folder / f"llm-smoke-{today}.json"
        if path.exists():
            raise LLMProbeError("daily_llm_attempt_limit")
        state = {"date": today, "checkedAt": checked_at, "ok": False,
                 "keyFingerprint": signature, "model": model, "requestAttempts": 1}
        save(path, state)  # 请求前占位；超时或断连也不自动重试。
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 16,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return one JSON object only."},
                {"role": "user", "content": 'Return exactly {"ok":true}.'},
            ],
        }
        payload.update(model_request_options(model))
        try:
            response = send(payload)
            usage = _safe_usage(response.get("usage"))
            if usage:
                state["usage"] = usage
            choices = response.get("choices")
            content = (choices[0].get("message") or {}).get("content") if isinstance(choices, list) and choices else None
            if parse_output(content or "") != {"ok": True}:
                raise LLMProbeError("structured_result_invalid")
            state["ok"] = True
        except LLMProbeError as exc:
            state["error"] = exc.code
        except (KeyError, TypeError, IndexError):
            state["error"] = "invalid_response"
        save(path, state)
        return state
