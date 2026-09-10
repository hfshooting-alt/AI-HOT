"""公司与产品库的字段、预算和时间配置。"""
from datetime import datetime
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 1
PROMPT_VERSION = 4
SCALAR_FIELDS = (
    "founded", "country", "team", "business", "investors",
    "total_funding", "valuation",
)
ALL_EVIDENCE_FIELDS = ("company_name", "product_names", *SCALAR_FIELDS)
DEFAULTS = {
    "content_input_chars": 8000,
    "timeout_seconds": 90,
    "concurrency": 2,
    "budget_seconds": 300,
    "max_new_articles_per_run": 20,
}


def overview_cfg(tx: dict) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (tx.get("companyOverview") or {}).items()
                if not k.startswith("_")})
    return cfg


def now_bj_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
