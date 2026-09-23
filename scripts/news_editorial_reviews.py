"""Apply evidence-bound summary reviews to a copy of an enrichment result."""
import copy
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_summary_review(item, result, rules=None):
    """Project an exact reviewed correction without changing inputs or caches.

    The source body wins over a supplied digest. Metadata-only callers may use
    the full contentSha256 already attached to their processed article.
    """
    output = copy.deepcopy(result)
    if rules is None:
        path = ROOT / "config/quality_review.json"
        rules = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    decisions = rules.get("articleSummaryReviews", []) if isinstance(rules, dict) else rules
    if not isinstance(decisions, list):
        raise ValueError("articleSummaryReviews must be a list")

    body = item.get("content_text")
    content_sha = _sha(body) if isinstance(body, str) and body else item.get("contentSha256")
    summary = result.get("summary")
    binding = {"articleId": item.get("id"), "title": item.get("title"),
               "url": item.get("url"), "contentSha256": content_sha}
    if (not all(isinstance(value, str) and value for value in binding.values())
            or not re.fullmatch(r"[0-9a-f]{64}", content_sha)
            or not isinstance(summary, str) or not summary):
        return output
    if (isinstance(body, str) and body and item.get("contentSha256")
            and item["contentSha256"] != content_sha):
        return output
    binding["fromSummarySha256"] = _sha(summary)
    matches = [decision for decision in decisions if isinstance(decision, dict)
               and all(decision.get(key) == value for key, value in binding.items())]
    if len(matches) > 1:
        raise ValueError("Duplicate matching article summary reviews")
    if not matches:
        return output

    decision = matches[0]
    # Imported only after a match, so enrich_news may call this after caching.
    from enrich_news import validate_summary
    taxonomy = json.loads((ROOT / "config/taxonomy.json").read_text(encoding="utf-8"))
    if not validate_summary(taxonomy, decision.get("toSummary")):
        raise ValueError("Reviewed article summary failed validation")
    if any(not isinstance(decision.get(key), str) or not decision[key].strip()
           for key in ("reviewedAt", "reason")):
        raise ValueError("Article summary review lacks attribution")
    output.update(summary=decision["toSummary"], summaryOrigin="editorial_review",
                  editorialReview={"reviewedAt": decision["reviewedAt"],
                                   "reason": decision["reason"],
                                   "origin": "source-grounded-review"})
    return output
