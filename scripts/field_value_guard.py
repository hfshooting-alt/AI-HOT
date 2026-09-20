"""Quarantine explicit field-meaning conflicts without rewriting model caches.

This deliberately does not infer funding scope from an amount or article title.
Unqualified amounts remain reviewable; only clear round/fund-size or market-cap
labels are rejected from the incompatible company scalar field.
"""
import re


_TOTAL_QUALIFIER = re.compile(
    r"累计|累积|合计|共计|总计|"
    r"total\s+(?:funding|raised)|(?:raised|funding)\s+in\s+total|"
    r"(?:raised|funding).{0,30}\bto\s+date\b|aggregate\s+funding",
    re.IGNORECASE,
)
_ROUND = re.compile(
    r"(?:pre[-‐‑–— ]?)?[a-z](?:\+|\d+)?\s*轮|"
    r"(?:种子|天使)(?:轮|融资)|(?:本|该|此|单|某|首|新一)轮|"
    r"第[一二三四五六七八九十百\d]+轮|"
    r"\bseries\s+[a-z](?:\+|\d+)?\b|"
    r"(?<![a-z])(?:pre[-‐‑–— ]?)?seed(?![a-z])|"
    r"\bangel\s+(?:round|funding|financing)\b|\b(?:this|single)\s+round\b",
    re.IGNORECASE,
)
_FUND_SIZE = re.compile(
    r"(?:首|第?[一二三四五六七八九十百\d]+)(?:期|支|号)基金|"
    r"基金(?:总)?规模|(?:基金(?:募集|募资)|募集.{0,12}基金)|"
    r"\bfund\s+size\b|\b(?:first|inaugural|debut)\s+fund\b|"
    r"\bfund\s+(?:[ivx]+|\d+)\b",
    re.IGNORECASE,
)
_MARKET_CAP = re.compile(r"市值|\bmarket\s*cap(?:itali[sz]ation)?\b", re.IGNORECASE)
_REASONS = {
    "single_round_not_total": "单轮融资金额不能作为累计融资",
    "fund_size_not_company_total": "基金规模不能作为公司累计融资",
    "market_cap_not_valuation": "市值不能作为公司估值",
}


def rejection_reason(field: str, value) -> str | None:
    """Return a narrow reason code, leaving ambiguous/ordinary values untouched."""
    if not isinstance(value, str) or not value.strip():
        return None
    if field == "valuation":
        return "market_cap_not_valuation" if _MARKET_CAP.search(value) else None
    if field != "total_funding":
        return None
    # An aggregate can legitimately mention its constituent rounds. The generic
    # '融资总额' alone also describes a round and is not a cumulative qualifier.
    if _TOTAL_QUALIFIER.search(value):
        return None
    if _FUND_SIZE.search(value):
        return "fund_size_not_company_total"
    if _ROUND.search(value):
        return "single_round_not_total"
    return None


def _source(article: dict) -> dict:
    return {
        "articleId": article.get("articleId") or article.get("id") or "",
        "url": article.get("url") or "",
        "title": article.get("title") or "",
        "publishedAt": article.get("publishedAt") or "",
        "sourceName": article.get("sourceName") or article.get("mpName") or "",
    }


def _quarantine(row: dict, field: str, value, reason: str, source: dict) -> None:
    entry = {"field": field, "originalValue": value, "reasonCode": reason,
             "reason": _REASONS[reason], **source}
    bucket = row.setdefault("fieldQuarantines", [])
    if entry not in bucket:
        bucket.append(entry)


def guard_value(row: dict, field: str, value, article: dict):
    """Record rejected article evidence on the merged row and return None."""
    reason = rejection_reason(field, value)
    if reason:
        _quarantine(row, field, value, reason, {**_source(article), "origin": "article"})
        return None
    return value


def guard_existing_values(row: dict) -> None:
    """Sanitize a copied previous row, keeping exact or explicitly unknown origin.

    Matching field evidence identifies the contributor. Associated articles alone
    do not, so the fallback records them as associations of a previous record.
    """
    for field in ("total_funding", "valuation"):
        current = row.get(field)
        current_reason = rejection_reason(field, current)
        matched_current = False
        sources = row.get("fieldSources", {}).get(field, [])
        kept = []
        for source in sources:
            value = source.get("value")
            reason = rejection_reason(field, value)
            if reason:
                _quarantine(row, field, value, reason,
                            {**_source(source), "origin": source.get("origin") or "article"})
                matched_current = matched_current or value == current
            else:
                kept.append(source)
        if len(kept) != len(sources):
            row["fieldSources"][field] = kept
        if current_reason:
            if not matched_current:
                _quarantine(row, field, current, current_reason, {
                    "origin": "previous_record",
                    "sourceArticles": [_source(s) for s in row.get("sourceArticles", [])],
                })
            row[field] = None
