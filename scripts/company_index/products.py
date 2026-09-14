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
