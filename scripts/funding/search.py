"""融资流水线：search。"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import tag_news
from llm_common import ensure_env_loaded, parse_output
from .config import search_cfg, funding_cfg, COMPANY_FIELDS, FIELD_LABELS


# ================= Tavily 搜索补全 =================

def tavily_search(query: str, api_key: str, max_results: int,
                  timeout_seconds: int = 30) -> list[dict]:
    """Tavily /search：返回 [{title, url, content}]；失败抛异常由上层处理。"""
    body = {"query": query, "max_results": max_results, "search_depth": "basic"}
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    return [r for r in (d.get("results") or []) if r.get("url")]


def build_search_prompt(tx: dict, rec: dict, missing: list[str],
                        search_results: list[dict]) -> tuple[str, str]:
    lines = [
        "你是融资信息研究员。根据搜索结果补全公司信息表中缺失的字段。",
        "",
        "## 需要补全的字段",
    ]
    for f in missing:
        lines.append(f"- {f}（{FIELD_LABELS[f]}）")
    lines += [
        "",
        "## 约束",
        "- 只使用搜索结果中明确出现的信息；搜索结果也没有的字段输出 null",
        "- 金额、估值、时间保留原文表述，禁止换算或臆造",
        "",
        "## 输出格式",
        '只输出一个 JSON 对象，键为需要补全的字段名，值为字符串或 null：'
        + json.dumps({f: "..." for f in missing}, ensure_ascii=False),
    ]
    system = "\n".join(lines)
    known = [f"{FIELD_LABELS[f]}：{rec[f]}" for f in COMPANY_FIELDS if rec.get(f)]
    snippets = []
    for i, r in enumerate(search_results[:5], 1):
        text = (r.get("content") or "")[:1500]
        snippets.append(f"[{i}] {r.get('title') or ''}\n{r.get('url')}\n{text}")
    user = (f"公司：{rec['company_name']}\n"
            + ("已知信息：\n" + "\n".join(known) + "\n" if known else "")
            + "\n搜索结果：\n" + "\n\n".join(snippets))
    return system, user


def apply_search_fill(tx: dict, rec: dict, search_fn, llm_fn) -> None:
    """对单个公司：1 次搜索 + 1 次 LLM 综合，填充缺失字段并留痕。"""
    scfg = search_cfg(tx)
    missing = [f for f in COMPANY_FIELDS if not rec.get(f)]
    if not missing:
        return
    product = rec.get("product_name") or ""
    query = f"{rec['company_name']} {product} 融资 投资方 估值".strip()
    try:
        results = search_fn(query, scfg["max_results"])
    except Exception as exc:  # noqa: BLE001 - 搜索失败不中断
        print(f"    搜索失败（{rec['company_name']}）: {exc}", file=sys.stderr)
        return
    if not results:
        return
    system, user = build_search_prompt(tx, rec, missing, results)
    try:
        raw = parse_output(llm_fn(tx, system, user,
                                  timeout_seconds=funding_cfg(tx)["timeout_seconds"]))
    except Exception as exc:  # noqa: BLE001
        print(f"    搜索综合失败（{rec['company_name']}）: {exc}", file=sys.stderr)
        return
    filled = []
    if isinstance(raw, dict):
        for f in missing:
            v = raw.get(f)
            if isinstance(v, str) and v.strip():
                rec[f] = v.strip()
                filled.append(f)
    rec["filledBySearch"] = filled
    urls: list[str] = []
    for r in results:
        if r.get("url") and r["url"] not in urls:
            urls.append(r["url"])
    rec["searchSources"] = urls


def fill_missing_fields(tx: dict, companies: list[dict], search_fn, llm_fn,
                        cache_path: Path | str) -> int:
    """搜索补全（缓存 TTL 内直接套用上次结果）。返回发起搜索的公司数。"""
    scfg = search_cfg(tx)
    cache_path = Path(cache_path)
    ttl = int(scfg.get("cache_ttl_days", 7)) * 86400
    cache = tag_news.load_cache(str(cache_path))
    now = time.time()
    searched = 0
    cfg = funding_cfg(tx)
    with ThreadPoolExecutor(max_workers=cfg["concurrency"]) as ex:
        futs = {}
        for rec in companies:
            if not any(not rec.get(f) for f in COMPANY_FIELDS):
                continue  # 无缺失
            hit = cache.get(rec["id"])
            if hit and now - hit.get("fetchedAtTs", 0) < ttl:
                for f, v in (hit.get("filled") or {}).items():
                    if rec.get(f) is None and isinstance(v, str) and v:
                        rec[f] = v
                        if f not in rec["filledBySearch"]:
                            rec["filledBySearch"].append(f)
                for u in hit.get("sources") or []:
                    if u not in rec["searchSources"]:
                        rec["searchSources"].append(u)
                continue
            searched += 1
            futs[ex.submit(apply_search_fill, tx, rec, search_fn, llm_fn)] = rec
        for fut in as_completed(futs):
            rec = futs[fut]
            fut.result()
            if rec.get("filledBySearch"):
                cache[rec["id"]] = {
                    "fetchedAtTs": int(now),
                    "filled": {f: rec[f] for f in rec["filledBySearch"]},
                    "sources": rec.get("searchSources") or [],
                }
    tag_news.save_cache(str(cache_path), cache)
    return searched


def make_search_fn(tx: dict):
    """构造真实搜索函数；未配置 key 时返回 None（调用方跳过搜索）。"""
    ensure_env_loaded()
    scfg = search_cfg(tx)
    api_key = os.environ.get(scfg["api_key_env"], "").strip()
    if not api_key:
        return None

    def _search(query: str, max_results: int) -> list[dict]:
        return tavily_search(query, api_key, max_results)

    return _search
