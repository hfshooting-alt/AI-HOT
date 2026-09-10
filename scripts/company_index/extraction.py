"""使用一次受预算控制的模型调用，从每篇文章抽取公司和产品。"""
import hashlib
import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import tag_news
from llm_common import parse_output
from .config import PROMPT_VERSION, SCALAR_FIELDS, overview_cfg


def build_prompt(tx: dict, article: dict) -> tuple[str, str]:
    industries = " / ".join(
        f"{v['id']}({v['label']})" for v in tx["dimensions"]["industry"]["values"])
    fields = "\n".join(f"- {field}：字符串或 null" for field in SCALAR_FIELDS)
    system = f"""你是公司与产品情报库抽取引擎。读取新闻并抽取新闻核心事件直接涉及的公司和产品。

只保留新闻核心主体：标题或核心事件中的公司、融资/上市/产品发布/团队变动的直接当事公司，以及明确归属于它的产品。不要收录仅作为投资方、财务顾问、交易所、供应商、媒体来源、同业对比或背景材料出现的公司。一篇融资或上市新闻通常只输出融资或拟上市主体；没有合格核心主体时 companies 为空数组。
对多事件早报逐条识别 AI 相关事件，只收录这些事件的核心公司与产品，跳过普通电商、汽车销量、游戏榜单等无 AI 关联事件。

每家公司一条记录：
- company_name：文章采用的公司名称，必填
- aliases：文章明确给出的别名、英文名或简称，字符串数组
- product_names：该公司在文章中明确关联的产品名称，字符串数组；无法确认归属时不要猜测
{fields}
- industry_id：按该公司自身业务选择，只能取 {industries}；不得直接继承整篇文章的行业标签，无法判定时取 ai_other

只使用文章明确表达的事实。缺失字段为 null，数组缺失为 []。不得根据常识补全，不得把媒体来源本身当作被报道公司。
country 必须是公司所属国家而不是市场覆盖范围。total_funding 是累计融资，不能把单轮融资填为累计融资；valuation 保留币种与估值时点，不能使用市值代替。不要以模型记忆补全团队和成立时间。
只输出 JSON：{{"companies":[{{"company_name":"...","aliases":[],"product_names":[],"founded":null,"country":null,"team":null,"business":null,"investors":null,"total_funding":null,"valuation":null,"industry_id":"ai_other"}}]}}"""
    cfg = overview_cfg(tx)
    user = (f"标题：{article['title']}\n来源：{article['sourceName']}\n"
            f"发布时间：{article.get('publishedAt') or '未知'}（今年/去年以此时间为基准；未知时保留相对时间）\n"
            f"类别：{article['category']}\n\n正文：\n"
            f"{article['content_text'][:cfg['content_input_chars']]}")
    return system, user


def normalize_company(raw: dict, tx: dict) -> dict | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("company_name"), str):
        return None
    name = raw["company_name"].strip()
    if not name:
        return None
    out = {"company_name": name}
    for field in ("aliases", "product_names"):
        values = raw.get(field)
        out[field] = list(dict.fromkeys(v.strip() for v in values
                                        if isinstance(v, str) and v.strip())) if isinstance(values, list) else []
    for field in SCALAR_FIELDS:
        value = raw.get(field)
        out[field] = value.strip() if isinstance(value, str) and value.strip() else None
    valid = {v["id"] for v in tx["dimensions"]["industry"]["values"]}
    out["industry_id"] = raw.get("industry_id") if raw.get("industry_id") in valid else "ai_other"
    return out


def cache_key(tx: dict, article: dict) -> str:
    cfg = overview_cfg(tx)
    raw = "|".join((str(PROMPT_VERSION), str((tx.get("model") or {}).get("model", "")),
                    article["id"], hashlib.sha256(article["content_text"].encode()).hexdigest(),
                    str(cfg["content_input_chars"])))
    return hashlib.sha256(raw.encode()).hexdigest()


def extract_one(tx: dict, article: dict, llm_fn) -> dict:
    if len((article.get("content_text") or "").strip()) < 20:
        return {"status": "failed", "companies": [], "reason": "文章内容不足"}
    system, user = build_prompt(tx, article)
    try:
        raw = parse_output(llm_fn(tx, system, user,
                                  timeout_seconds=overview_cfg(tx)["timeout_seconds"]))
        if not isinstance(raw, dict) or not isinstance(raw.get("companies"), list):
            raise ValueError("模型输出结构不合法")
        companies = [c for c in (normalize_company(v, tx) for v in raw["companies"]) if c]
        return {"status": "complete", "companies": companies}
    except Exception as exc:  # noqa: BLE001 - 单篇失败由统计与发布门槛处理
        return {"status": "failed", "companies": [], "reason": str(exc)[:160]}


def extract_articles(tx: dict, articles: list[dict], cache_path, llm_fn) -> tuple[dict, dict]:
    """只缓存成功结果；每轮新调用数和总耗时有硬上限。"""
    cache = tag_news.load_cache(str(cache_path))
    results, pending = {}, []
    cache_hits = 0
    for article in articles:
        hit = cache.get(cache_key(tx, article))
        if hit and hit.get("status") == "complete":
            results[article["id"]] = hit
            cache_hits += 1
        else:
            pending.append(article)
    cfg = overview_cfg(tx)
    selected = pending[:max(0, int(cfg["max_new_articles_per_run"]))]
    deferred = pending[len(selected):]
    for article in deferred:
        results[article["id"]] = {"status": "pending", "companies": [], "reason": "超过本轮调用上限"}
    started = time.monotonic()
    calls = 0
    timed_out = []
    queue = iter(selected)
    with ThreadPoolExecutor(max_workers=max(1, int(cfg["concurrency"]))) as pool:
        futures = {}

        def submit_next():
            nonlocal calls
            try:
                article = next(queue)
            except StopIteration:
                return False
            calls += 1
            futures[pool.submit(extract_one, tx, article, llm_fn)] = article
            return True

        for _ in range(max(1, int(cfg["concurrency"]))):
            if not submit_next():
                break
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                article = futures.pop(future)
                result = future.result()
                results[article["id"]] = result
                if result["status"] == "complete":
                    cache[cache_key(tx, article)] = result
            if time.monotonic() - started < float(cfg["budget_seconds"]):
                for _ in range(len(done)):
                    if not submit_next():
                        break
            else:
                timed_out.extend(queue)
                break
        # 已提交的调用必须收口并记录，不能把正在消费的任务伪装成未调用。
        for future, article in list(futures.items()):
            result = future.result()
            results[article["id"]] = result
            if result["status"] == "complete":
                cache[cache_key(tx, article)] = result
    for article in timed_out:
        results[article["id"]] = {"status": "pending", "companies": [], "reason": "超过本轮时间预算"}
    tag_news.save_cache(str(cache_path), cache)
    return results, {"modelCalls": calls, "cacheHits": cache_hits,
                     "articlesDeferred": len(deferred) + sum(
                         1 for a in selected if results.get(a["id"], {}).get("status") == "pending")}
