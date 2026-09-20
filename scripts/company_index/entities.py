"""公司实体合并、产品归属和逐字段来源留痕。"""
import copy
import hashlib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from field_value_guard import guard_existing_values, guard_value
from funding.companies import normalize_company_key, _country_to_region_label
from .config import ALL_EVIDENCE_FIELDS, SCALAR_FIELDS


def entity_id(key: str) -> str:
    return "company:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def timestamp(value):
    try:
        dt = datetime.fromisoformat((value or '').replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo('Asia/Shanghai'))).timestamp()
    except (ValueError, TypeError):
        return float('-inf')


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
                   tx: dict, research_rules: dict | None = None) -> list[dict]:
    from .products import merge_updates, refresh
    from .identity import RULES_PATH
    if research_rules is None:
        research_rules = json.loads(RULES_PATH.read_text(encoding='utf-8')) if RULES_PATH.exists() else {}
    divisions = {normalize_company_key(r['record_name']): r
        for r in research_rules.get('records', [])
        if research_rules.get('checkedAt') and r.get('reviewed') is True
        and r.get('source_kind') == 'division' and r.get('record_name') and r.get('owner_company')
        and normalize_company_key(r['record_name']) != normalize_company_key(r['owner_company'])
        and any(f.get('field') == 'owner_company' and f.get('value') == r['owner_company']
                and f.get('quote') and f.get('url', '').startswith('https://')
                and f.get('verificationStatus') != 'provisional' for f in r.get('facts', []))}
    companies = {r["id"]: copy.deepcopy(r) for r in previous.get("companies", [])
                 if isinstance(r, dict) and str(r.get("id", "")).startswith("company:")}
    lookup = {}
    for rec in companies.values():
        rec.setdefault("aliases", [])
        rec.setdefault("product_names", [])
        rec.setdefault("fieldSources", {})
        rec.setdefault("sourceArticles", [])
        guard_existing_values(rec)
        for name in [rec.get("company_name", ""), *rec["aliases"]]:
            key = normalize_company_key(name)
            if key:
                lookup[key] = rec["id"]
    industry_labels = {v["id"]: v["label"] for v in tx["dimensions"]["industry"]["values"]}
    for article in sorted(articles, key=lambda a: timestamp(a.get("publishedAt"))):
        for item in (extracts.get(article["id"]) or {}).get("companies") or []:
            names = [item["company_name"], *item.get("aliases", [])]
            keys = [normalize_company_key(n) for n in names if normalize_company_key(n)]
            division = divisions.get(keys[0])
            if division:
                # Reviewed departments must survive until identity review. An
                # owner's alias must not receive a department's scalar fields.
                rid = next((r['id'] for r in companies.values()
                            if normalize_company_key(r['company_name']) == keys[0]), entity_id(keys[0]))
                if rid not in companies:
                    owner = next((r for r in companies.values() if normalize_company_key(r['company_name'])
                                  == normalize_company_key(division['owner_company'])), {})
                    profile = owner.get('brandProfiles', {}).get(division['record_name'])
                    if isinstance(profile, dict):
                        companies[rid] = copy.deepcopy(profile)
                        companies[rid].update(id=rid, company_name=division['record_name'])
                        guard_existing_values(companies[rid])
            else:
                rid = next((lookup[k] for k in keys if k in lookup and k not in divisions), None)
            if rid is None or rid not in companies:
                rid = rid or entity_id(keys[0])
                companies[rid] = {
                    "id": rid, "company_name": division['record_name'] if division else item["company_name"], "aliases": [],
                    "product_names": [], **{f: None for f in SCALAR_FIELDS},
                    "dims": {"行业": "其他AI应用", "国家/地区": "其他"},
                    "fieldSources": {}, "sourceArticles": [],
                    "firstSeenAt": article.get("publishedAt") or "",
                    "lastSeenAt": article.get("publishedAt") or "",
                }
            rec = companies[rid]
            if division:
                rec['company_name'] = division['record_name']
            is_latest = timestamp(article.get('publishedAt')) >= timestamp(rec.get('lastSeenAt'))
            incoming_type = item.get('entity_type', 'company')
            # A product alias (e.g. a known company's app) can update that company
            # without turning the company itself into an unassigned product.
            product_alias = (incoming_type == 'product' and rec.get('entityType') == 'company'
                             and normalize_company_key(rec['company_name']) != keys[0])
            if not product_alias and (is_latest or not rec.get('entityType')):
                rec['entityType'] = incoming_type
            for key in keys:
                if (division and key == keys[0]) or (not division and key not in divisions):
                    lookup[key] = rid
            for alias in names:
                if alias != rec["company_name"] and alias not in rec["aliases"]:
                    rec["aliases"].append(alias)
            if is_latest:
                rec['lastSeenAt'] = article.get('publishedAt') or rec.get('lastSeenAt') or ''
            rec["firstSeenAt"] = min(filter(None, [rec.get("firstSeenAt"), article.get("publishedAt")] ), key=timestamp) \
                if rec.get("firstSeenAt") and article.get("publishedAt") else (rec.get("firstSeenAt") or article.get("publishedAt") or "")
            _add_evidence(rec, "company_name", item["company_name"], article)
            for product in item.get("product_names", []):
                product_key = re.sub(r"\s+", "", product).casefold()
                if not any(re.sub(r"\s+", "", p).casefold() == product_key for p in rec["product_names"]):
                    rec["product_names"].append(product)
                _add_evidence(rec, "product_names", product, article)
            merge_updates(rec, item, article)
            for field in SCALAR_FIELDS:
                value = guard_value(rec, field, item.get(field), article)
                if value and (is_latest or not rec.get(field)):
                    rec[field] = value
                    _add_evidence(rec, field, value, article)
            industry = industry_labels.get(item.get("industry_id"), "其他AI应用")
            if is_latest:
                rec["dims"]["行业"] = industry
            # Country already follows the newest-value/older-gap-fill rule above.
            # Derive its dimension from that selected value, not an older input.
            company_region = _country_to_region_label(rec.get("country"))
            region = company_region
            if region != "其他" or rec["dims"].get("国家/地区") == "其他":
                rec["dims"]["国家/地区"] = region
            if not any(s.get("id") == article["id"] for s in rec["sourceArticles"]):
                rec["sourceArticles"].append({"id": article["id"], "title": article.get("title") or "",
                    "url": article.get("url") or "", "publishedAt": article.get("publishedAt") or "",
                    "sourceName": article.get("sourceName") or "", "category": article.get("category") or ""})
    rows = sorted(companies.values(), key=lambda r: timestamp(r.get("lastSeenAt")), reverse=True)
    for rec in rows:
        refresh(rec)
        rec['updatedAt'] = rec.get('lastSeenAt') or ''
        rec["sourceArticles"].sort(key=lambda s: timestamp(s.get("publishedAt")), reverse=True)
        for field in ALL_EVIDENCE_FIELDS:
            if field in rec["fieldSources"]:
                rec["fieldSources"][field].sort(key=lambda e: e.get("publishedAt") or "", reverse=True)
    return rows
