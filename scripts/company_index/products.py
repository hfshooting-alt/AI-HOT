"""Product relationships are article-level facts, not inferred ownership."""
import re
from .entities import timestamp

RELATIONS = {"owned", "integrated", "used", "unknown"}

def key(name):
    return re.sub(r"\s+", "", name).casefold()

def normalize(raw, article=None):
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            continue
        if item.get("kind") in {"paper", "algorithm", "method"}:
            continue
        relation = item.get("relationship", "unknown")
        quote = item.get("quote", "")
        if relation not in RELATIONS or not isinstance(quote, str) or not quote.strip():
            relation, quote = "unknown", ""
        if article and quote and quote not in (article.get("title", "") + "\n" + article.get("content_text", "")):
            relation, quote = "unknown", ""
        out.append({"name": item["name"].strip(), "relationship": relation, "quote": quote})
    return out

def refresh(rec):
    updates = rec.setdefault("productUpdates", [])
    for name in rec.get("product_names", []):
        evidence = [e for e in rec.get("fieldSources", {}).get("product_names", []) if key(e["value"]) == key(name)]
        if not evidence and any(key(u["name"]) == key(name) for u in updates):
            continue
        for e in evidence or [{}]:
            if not any(key(u["name"]) == key(name) and u.get("articleId", "") == e.get("articleId", "") for u in updates):
                updates.append({"name": name, "relationship": "unknown", "quote": "", **{f: e.get(f, "") for f in ("articleId", "url", "publishedAt", "title")}})
    updates.sort(key=lambda u: timestamp(u.get("publishedAt")), reverse=True)
    names = {}
    for u in updates:
        names.setdefault(key(u["name"]), u["name"])
    rec["product_names"] = list(names.values())
    return rec

def merge_updates(rec, item, article):
    updates = rec.setdefault("productUpdates", [])
    for value in item.get("products", []):
        u = dict(value, articleId=article["id"], url=article.get("url", ""), title=article.get("title", ""), publishedAt=article.get("publishedAt", ""))
        updates[:] = [old for old in updates if not (key(old["name"]) == key(u["name"]) and old.get("articleId") == article["id"])]
        updates.append(u)
    refresh(rec)


def guard_integrated_product_identities(companies):
    """A same-name supplier needs more than another company's integration evidence.

    Preserve the product when its sole ownership quote describes the integrated
    tool itself. This is a narrow evidence guard, not a company name dictionary.
    """
    integrated = {key(p["name"]) for c in companies for p in c.get("products", [])
                  if p["relationship"] in {"integrated", "used"} and key(c["company_name"]) != key(p["name"])}
    for company in companies:
        name = key(company["company_name"])
        products = company.get("products", [])
        if company.get("entity_type") != "company" or name not in integrated or not products:
            continue
        if not all(key(p["name"]) == name for p in products):
            continue
        # A tool label is not an ownership assertion. Explicit company/team or
        # development/operation evidence keeps the company available for review.
        if any(re.search(r"公司|团队|开发|运营|旗下|成立|创办|创始|company|develop|operat|founded", p.get("quote", ""), re.I) for p in products):
            continue
        if not all(re.search(r"工具|产品|模型|应用|tool|product|model|app", p.get("quote", ""), re.I) for p in products):
            continue
        company["entity_type"] = "product"
        for product in products:
            product["relationship"] = "unknown"
    return companies


def replace_article_products(previous, article_ids):
    """Remove only superseded article contributions before merging new results.

    Keep other days, failed extractions, unscoped legacy names and reviewed
    research evidence. The caller supplies successfully reprocessed article IDs.
    """
    import copy
    result = copy.deepcopy(previous)
    for rec in result.get("companies", []):
        sources = rec.setdefault("fieldSources", {})
        evidence = sources.get("product_names", [])
        updates = rec.get("productUpdates", [])
        removed = {key(e["value"]) for e in evidence if e.get("articleId") in article_ids and e.get("origin") != "research"}
        removed.update(key(u["name"]) for u in updates if u.get("articleId") in article_ids)
        sources["product_names"] = [e for e in evidence if e.get("articleId") not in article_ids or e.get("origin") == "research"]
        rec["productUpdates"] = [u for u in updates if u.get("articleId") not in article_ids]
        surviving = {key(e["value"]) for e in sources["product_names"]}
        surviving.update(key(u["name"]) for u in rec["productUpdates"])
        rec["product_names"] = [p for p in rec.get("product_names", []) if key(p) not in removed or key(p) in surviving]
    return result
