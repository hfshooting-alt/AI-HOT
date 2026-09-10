"""单条新闻分类业务探针；一次请求、无重试、不保存新闻正文。"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from automation.publish import save
from llm_common import model_request_options, parse_output, resolve_model
from tag_news import build_prompt, validate
from testing.llm_probe import LLMProbeError, _safe_usage, request
from testing.manus_probe import locked


def smoke(root: Path, tx: dict, case_path: Path, *, allow_paid=False,
          send=None, today=None, now=None) -> dict:
    if not allow_paid:
        raise LLMProbeError("paid_opt_in_required")
    case = json.loads(case_path.read_text(encoding="utf-8"))
    expected = case.get("expected")
    if not isinstance(expected, dict) or validate(tx, expected).get("autoFallback"):
        raise LLMProbeError("invalid_business_case")
    model_cfg = tx["model"]
    model = resolve_model(tx)
    key = os.getenv(model_cfg["api_key_env"], "").strip()
    if not key or key.lower().startswith("your-"):
        raise LLMProbeError("missing_api_key")
    base = (os.getenv(model_cfg["api_base_env"], "").strip()
            or model_cfg["default_base"]).rstrip("/")
    endpoint = base + "/chat/completions"
    send = send or (lambda payload: request(endpoint, key, payload))
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    signature = hashlib.sha256(f"{key}\0{base}\0{model}".encode()).hexdigest()
    with locked(root) as folder:
        path = folder / f"llm-business-smoke-{today}.json"
        if path.exists():
            raise LLMProbeError("daily_business_attempt_limit")
        state = {
            "date": today,
            "checkedAt": time.time() if now is None else now,
            "ok": False,
            "keyFingerprint": signature,
            "model": model,
            "sampleId": case["sampleId"],
            "caseVersion": case["caseVersion"],
            "requestAttempts": 1,
            "expected": expected,
        }
        save(path, state)
        system, user = build_prompt(tx, case["title"], case.get("summary") or "")
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        payload.update(model_request_options(model))
        try:
            response = send(payload)
            usage = _safe_usage(response.get("usage"))
            if usage:
                state["usage"] = usage
            choices = response.get("choices")
            content = ((choices[0].get("message") or {}).get("content")
                       if isinstance(choices, list) and choices else None)
            raw = parse_output(content or "")
            prediction = validate(tx, raw)
            state["prediction"] = {"category": prediction["category"],
                                   "tags": prediction["tags"]}
            state["structured"] = not prediction["autoFallback"]
            state["matchesExpected"] = state["prediction"] == expected
            state["ok"] = state["structured"] and state["matchesExpected"]
            if not state["structured"]:
                state["error"] = "structured_result_invalid"
            elif not state["matchesExpected"]:
                state["error"] = "business_case_mismatch"
        except LLMProbeError as exc:
            state["error"] = exc.code
        except (KeyError, TypeError, IndexError):
            state["error"] = "invalid_response"
        save(path, state)
        return state
