"""公司实体合并、产品归属和逐字段来源留痕。"""
import copy
import hashlib

from funding.companies import normalize_company_key, _country_to_region_label
from .config import ALL_EVIDENCE_FIELDS, SCALAR_FIELDS


def entity_id(key: str) -> str:
    return "company:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _source(article: dict, value: str) -> dict:
    return {"value": value, "articleId": article["id"], "url": article.get("url") or "",
            "title": article.get("title") or "", "publishedAt": article.get("publishedAt") or "",
            "sourceName": article.get("sourceName") or "", "origin": "article"}


def _add_evidence(rec: dict, field: str, value: str, article: dict) -> None:
    if not value:
        return
    bucket = rec["fieldSources"].setdefault(field, [])
    ev = _source(article, value)
    if not any(x.get("articleId") == ev["articleId"] and x.get("value") == value for x in bucket):
        bucket.append(ev)


def merge_entities(articles: list[dict], extracts: dict[str, dict], previous: dict,
                   tx: dict) -> list[dict]:
    companies = {r["id"]: copy.deepcopy(r) for r in previous.get("companies", [])
                 if isinstance(r, dict) and str(r.get("id", "")).startswith("company:")}
    lookup = {}
    for rec in companies.values():
        rec.setdefault("aliases", [])
        rec.setdefault("product_names", [])
        rec.setdefault("fieldSources", {})
        rec.setdefault("sourceArticles", [])
        for name in [rec.get("company_name", ""), *rec["aliases"]]:
            key = normalize_company_key(name)
            if key:
                lookup[key] = rec["id"]
    industry_labels = {v["id"]: v["label"] for v in tx["dimensions"]["industry"]["values"]}
    for article in sorted(articles, key=lambda a: a.get("publishedAt") or ""):
        for item in (extracts.get(article["id"]) or {}).get("companies") or []:
            names = [item["company_name"], *item.get("aliases", [])]
            keys = [normalize_company_key(n) for n in names if normalize_company_key(n)]
            rid = next((lookup[k] for k in keys if k in lookup), None)
            if rid is None:
                rid = entity_id(keys[0])
                companies[rid] = {
                    "id": rid, "company_name": item["company_name"], "aliases": [],
                    "product_names": [], **{f: None for f in SCALAR_FIELDS},
                    "dims": {"行业": "其他AI应用", "国家/地区": "其他"},
                    "fieldSources": {}, "sourceArticles": [],
                    "firstSeenAt": article.get("publishedAt") or "",
                    "lastSeenAt": article.get("publishedAt") or "",
                }
            rec = companies[rid]
            for key in keys:
                lookup[key] = rid
            for alias in names:
                if alias != rec["company_name"] and alias not in rec["aliases"]:
                    rec["aliases"].append(alias)
            rec["lastSeenAt"] = max(rec.get("lastSeenAt") or "", article.get("publishedAt") or "")
            rec["firstSeenAt"] = min(filter(None, [rec.get("firstSeenAt"), article.get("publishedAt")])) \
                if rec.get("firstSeenAt") and article.get("publishedAt") else (rec.get("firstSeenAt") or article.get("publishedAt") or "")
            _add_evidence(rec, "company_name", item["company_name"], article)
            for product in item.get("product_names", []):
                if product not in rec["product_names"]:
                    rec["product_names"].append(product)
                _add_evidence(rec, "product_names", product, article)
            for field in SCALAR_FIELDS:
                value = item.get(field)
                if value:
                    rec[field] = value
                    _add_evidence(rec, field, value, article)
            industry = industry_labels.get(item.get("industry_id"), "其他AI应用")
            rec["dims"]["行业"] = industry
            company_region = _country_to_region_label(item.get("country"))
            region = (company_region if company_region != "其他"
                      else (article.get("dims") or {}).get("国家/地区") or "其他")
            if region != "其他" or rec["dims"].get("国家/地区") == "其他":
                rec["dims"]["国家/地区"] = region
            if not any(s.get("id") == article["id"] for s in rec["sourceArticles"]):
                rec["sourceArticles"].append({"id": article["id"], "title": article.get("title") or "",
                    "url": article.get("url") or "", "publishedAt": article.get("publishedAt") or "",
                    "sourceName": article.get("sourceName") or "", "category": article.get("category") or ""})
    rows = sorted(companies.values(), key=lambda r: r.get("lastSeenAt") or "", reverse=True)
    for rec in rows:
        rec["sourceArticles"].sort(key=lambda s: s.get("publishedAt") or "", reverse=True)
        for field in ALL_EVIDENCE_FIELDS:
            if field in rec["fieldSources"]:
                rec["fieldSources"][field].sort(key=lambda e: e.get("publishedAt") or "", reverse=True)
    return rows
