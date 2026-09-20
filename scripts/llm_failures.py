"""Safe model failure diagnostics and a per-stage, latched queue circuit.

Never serialize exception messages, provider response bodies, URLs or headers.
Only newly attempted model results belong in the circuit; cache hits do not.
"""
import socket
import urllib.error


_CATEGORIES = frozenset({
    "authentication", "permission", "payment", "rate_limit", "endpoint",
    "request", "server", "http", "timeout", "network", "configuration",
    "invalid_response", "unknown", "content",
})
_IMMEDIATE = frozenset({
    "authentication", "permission", "payment", "rate_limit", "endpoint", "configuration",
})


class LLMRequestError(RuntimeError):
    """An error containing only an allowlisted category and optional HTTP status."""

    def __init__(self, category: str, http_status: int | None = None):
        self.category = category if category in _CATEGORIES else "unknown"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.category + (f" (HTTP {self.http_status})" if self.http_status else ""))


def safe_error(exc: Exception) -> dict:
    """Classify without reading or copying exception text or HTTP error bodies."""
    status = None
    if isinstance(exc, LLMRequestError):
        category, status = exc.category, exc.http_status
    elif isinstance(exc, urllib.error.HTTPError):
        status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        category = {401: "authentication", 403: "permission", 402: "payment",
                    404: "endpoint", 429: "rate_limit"}.get(status)
        if category is None:
            category = "server" if status and status >= 500 else "request" if status and status >= 400 else "http"
    elif isinstance(exc, (TimeoutError, socket.timeout)):
        category = "timeout"
    elif isinstance(exc, urllib.error.URLError):
        category = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "network"
    elif isinstance(exc, (ConnectionError, OSError)):
        category = "network"
    else:
        category = "unknown"
    return {"category": category, "httpStatus": status, "systemic": category in _IMMEDIATE}


class FailureCircuit:
    """Stop queued work on a systemic failure or consecutive model failures.

    observe expects {status: complete|failed, error: safe_error(exc)}.
    Content/evidence failures are local to an article and do not count.
    """

    def __init__(self, failure_limit: int = 3):
        self.failure_limit = max(1, int(failure_limit))
        self.failure_count = 0
        self.stopped = False
        self.reason = None

    def observe(self, result: dict) -> None:
        if self.stopped:
            return
        if result.get("status") == "complete":
            self.failure_count = 0
            return
        if result.get("status") != "failed":
            return
        error = result.get("error") or {}
        diagnostic = safe_error(LLMRequestError(error.get("category", "unknown"), error.get("httpStatus")))
        if diagnostic["category"] == "content":
            return
        self.failure_count += 1
        if diagnostic["systemic"] or self.failure_count >= self.failure_limit:
            self.stopped = True
            self.reason = diagnostic
