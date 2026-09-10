#!/usr/bin/env python3
"""在付费摘要与实体抽取前筛除与 AI 无实质关系的 Manus 文章。"""
import hashlib
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tag_news  # noqa: E402
from llm_common import call_llm, parse_output, resolve_model  # noqa: E402

DEFAULTS = {
    "content_input_chars": 5000,
    "timeout_seconds": 45,
    "concurrency": 2,
    "budget_seconds": 300,
    "max_new_items_per_run": 40,
    "max_output_tokens": 180,
}
PROMPT_VERSION = 1


def cfg(tx: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (tx.get("relevance") or {}).items() if not k.startswith("_")})
    return out


def item_key(item: dict) -> str:
    raw = "|".join((item.get("mpName") or item.get("source") or "",
                    item.get("published_date") or item.get("publishedAt") or "",
                    (item.get("title") or "").strip().lower()))
    return "rel:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def cache_key(tx: dict, item: dict) -> str:
    content = item.get("content_text") or ""
    raw = "|".join((str(PROMPT_VERSION), resolve_model(tx), item_key(item),
                    hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    str(cfg(tx)["content_input_chars"])))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_prompt(tx: dict, item: dict) -> tuple[str, str]:
    system = """你是 Garena 投资部 AI 新闻相关性筛选器。
判断文章的核心事件是否与人工智能有实质关系。以下情况为 relevant=true：AI 模型、AI 产品、AI 公司、AI 融资、AI 研究、AI 算力、AI 智能体、机器人或 AI 对游戏/社交/内容行业产生直接影响的事件。
仅在标题或正文顺带出现 AI、公司背景中提到 AI、普通游戏/电商/广告/影视/金融新闻没有具体 AI 事件时，必须为 relevant=false。
不要依据常识补充信息。evidence 必须逐字复制标题或正文中的一段连续原文，最多 80 字；无法给出证据时视为输出失败。
只输出 JSON：{"relevant":true,"reason":"一句简短理由","evidence":"原文证据"}"""
    c = cfg(tx)
    user = (f"标题：{item.get('title') or ''}\n来源：{item.get('mpName') or item.get('source') or ''}\n\n"
            f"正文：\n{(item.get('content_text') or '')[:c['content_input_chars']]}")
    return system, user


def source_evidence(evidence: str, *texts: str) -> str | None:
    """返回来源中的实际连续片段；仅容忍模型增删空白，不容忍改字。"""
    if not evidence:
        return None
    for text in texts:
        if evidence in text:
            return evidence
        compact, positions = [], []
        for index, char in enumerate(text):
            if not char.isspace():
                compact.append(char)
                positions.append(index)
        needle = "".join(char for char in evidence if not char.isspace())
        start = "".join(compact).find(needle)
        if start >= 0 and needle:
            actual = text[positions[start]:positions[start + len(needle) - 1] + 1]
            if len(actual) <= 80:
                return actual
    return None


def screen_one(tx: dict, item: dict, llm_fn=call_llm) -> dict:
    content = (item.get("content_text") or "").strip()
    title = (item.get("title") or "").strip()
    if len(content) < 50:
        return {"status": "failed", "relevant": None, "reason": "文章内容不足", "evidence": ""}
    system, user = build_prompt(tx, item)
    try:
        c = cfg(tx)
        raw = parse_output(llm_fn(tx, system, user, timeout_seconds=c["timeout_seconds"],
                                  max_tokens=c["max_output_tokens"]))
        if not isinstance(raw, dict) or not isinstance(raw.get("relevant"), bool):
            raise ValueError("模型输出缺少 relevant 布尔值")
        evidence = raw.get("evidence")
        reason = raw.get("reason")
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence.strip()) > 80:
            raise ValueError("evidence 缺失或过长")
        evidence = source_evidence(evidence.strip(), title, content)
        if evidence is None:
            raise ValueError("evidence 不是标题或正文中的连续原文")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason 缺失")
        return {"status": "complete", "relevant": raw["relevant"],
                "reason": reason.strip()[:120], "evidence": evidence}
    except Exception as exc:  # 单条失败留待下轮，不将不确定内容发布
        return {"status": "failed", "relevant": None, "reason": str(exc)[:160], "evidence": ""}


def screen_items(items: list[dict], tx: dict, cache_path: str | Path,
                 llm_fn=call_llm, max_new_items: int | None = None) -> tuple[dict[str, dict], dict]:
    """缓存优先；达到调用或耗时上限后，其余条目标记 pending。"""
    cache = tag_news.load_cache(str(cache_path))
    results: dict[str, dict] = {}
    pending = []
    hits = 0
    for item in items:
        hit = cache.get(cache_key(tx, item))
        if isinstance(hit, dict) and hit.get("status") == "complete":
            results[item_key(item)] = hit
            hits += 1
        else:
            pending.append(item)
    c = cfg(tx)
    limit = int(c["max_new_items_per_run"] if max_new_items is None else max_new_items)
    selected, deferred = pending[:max(0, limit)], pending[max(0, limit):]
    for item in deferred:
        results[item_key(item)] = {"status": "pending", "relevant": None,
                                   "reason": "超过本轮相关性筛选调用上限", "evidence": ""}
    started = time.monotonic()
    calls = 0
    queue = iter(selected)
    with ThreadPoolExecutor(max_workers=max(1, int(c["concurrency"]))) as pool:
        futures = {}

        def submit_next() -> bool:
            nonlocal calls
            if time.monotonic() - started >= c["budget_seconds"]:
                return False
            try:
                item = next(queue)
            except StopIteration:
                return False
            calls += 1
            futures[pool.submit(screen_one, tx, item, llm_fn)] = item
            return True

        for _ in range(max(1, int(c["concurrency"]))):
            if not submit_next():
                break
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                item = futures.pop(future)
                result = future.result()
                results[item_key(item)] = result
                if result.get("status") == "complete":
                    cache[cache_key(tx, item)] = result
                submit_next()
    for item in selected:
        results.setdefault(item_key(item), {"status": "pending", "relevant": None,
                                            "reason": "本轮时间预算已用完", "evidence": ""})
    tag_news.save_cache(str(cache_path), cache)
    stats = {
        "input": len(items), "cacheHits": hits, "calls": calls,
        "relevant": sum(r.get("relevant") is True for r in results.values()),
        "irrelevant": sum(r.get("relevant") is False for r in results.values()),
        "failed": sum(r.get("status") == "failed" for r in results.values()),
        "pending": sum(r.get("status") == "pending" for r in results.values()),
    }
    return results, stats
