#!/usr/bin/env python3
"""enrich_news.py — 正文加工 harness：一次模型调用同时产出 摘要 + 分类 + 标签。

复用 tag_news 的 taxonomy 加载、validate() 校验链与缓存思想；分类/标签不另起规则。
与 tag_news.py 的边界：
  - tag_news：标题+摘要各 800 字符的轻调用（AI HOT API 条目定稿后补标）
  - enrich_news：正文上限 enrich.content_input_chars（默认 16,000 字符）的重调用
    （Manus 公众号正文），预算/并发/超时全部走 taxonomy.json 的 enrich 配置块

用法:
    # 离线自检（不发请求）
    python3 scripts/enrich_news.py --selftest
"""
import argparse
import copy
import hashlib
import json
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tag_news  # noqa: E402
from llm_common import call_llm, parse_output  # noqa: E402
from llm_failures import FailureCircuit, safe_error
from upstream_briefs import is_brief, source_text

ENRICH_DEFAULTS = {
    "content_input_chars": 16000,
    "summary_min_chars": 100,
    "summary_sentence_min_chars": 60,
    "summary_max_chars": 220,
    "timeout_seconds": 90,
    "concurrency": 3,
    "budget_seconds": 900,
    "max_new_items_per_run": 20,
    "max_attempts": 1,
}
ENRICH_PROMPT_VERSION = 4
# 摘要中不允许出现的模型自述/Markdown 痕迹
SELF_REF_MARKERS = ("作为AI", "作为 AI", "作为语言模型", "我无法", "我不能")


def is_preview(title):
    return bool(re.search(r'预告|前瞻(?!性)|预热', title) and not re.search(r'已正式发布|现已上线', title))


def enforce_event_boundary(raw, title):
    """An explicit preview is not an actual release under the approved taxonomy."""
    if raw.get('category') == 'release' and is_preview(title):
        return {**raw, 'category': 'general', 'tags': {}, 'release_evidence': None}
    return raw


def enrich_cfg(tx: dict) -> dict:
    cfg = dict(ENRICH_DEFAULTS)
    cfg.update({k: v for k, v in (tx.get("enrich") or {}).items() if not k.startswith("_")})
    return cfg


# ================= 输入构造 =================

def build_enrich_prompt(tx: dict, title: str, mp_name: str, content: str) -> tuple[str, str]:
    """system 内嵌 taxonomy 全量 + 摘要约束；user 携带标题/公众号名/正文（截断到上限）。"""
    cfg = enrich_cfg(tx)
    lines = [
        "你是新闻加工引擎。对给定媒体文章执行两件事：",
        f"1. 写一段 {cfg['summary_min_chars']}—{cfg['summary_max_chars']} 字的中文事实摘要；",
        "2. 执行两级分类：先判定类别（6 选 1，互斥），再在该类别绑定的维度内各选 1 个取值。",
        "",
        "## 摘要约束",
        "- 只陈述文章中的事实，不评价、不预测、不添加文章没有的信息",
        "- 从具体事件或有正文依据的核心主线直接起笔，不重复标题、栏目名、作者、导语或版权声明；必须以完整句子结束",
        "- 对早报、速递等多事件汇编，通读全文并概括其中与 AI 有关的事件，不得只摘第一条；避免把非 AI 开场新闻当作主事件",
        "- 对历史回顾、人物访谈和长文，结合标题通读所给全文，围绕有正文依据的 AI 主线组织摘要；后半段的人才流向、产品或行业进展若属于该主线，也须覆盖，不得只摘开头的创业、失败或并购史。标题只作线索，不能据此补造 AI 关联。",
        "- 区分历史背景与本轮进展，保留原文日期、判断语气及观点归属；不得把回顾中的旧事件写成新发布或新融资。没有本轮新增事件时，按回顾或访谈概括，不强行制造新事件。",
        "- 不得使用 Markdown 标题、列表符号或链接",
        "- 不得出现“本文”“作者认为”之外的引导语，不得自述 AI 身份",
        "",
        "## 类别判定标准（按优先级从高到低排列；一条新闻同时命中多个标准时，必须归入优先级最高的类别）",
    ]
    for i, c in enumerate(tx["categories"], 1):
        lines.append(f"{i}. {c['id']}（{c['label']}）：{c['criteria']}")
    lines += ["", "## 类别绑定维度（每个维度必须且只能选 1 个取值）"]
    for c in tx["categories"]:
        if not c.get("dims"):
            lines.append(f"- {c['id']}：无维度，tags 必须为空对象 {{}}")
            continue
        parts = []
        for d in c["dims"]:
            dim = tx["dimensions"][d]
            vals = " | ".join(f"{v['id']}（{v['label']}）" for v in dim["values"])
            parts.append(f"{d}（{dim['label']}）取值：{vals}")
        lines.append(f"- {c['id']}：" + "；".join(parts))
    lines += [
        "",
        "## 约束",
        "- 先识别文章主事件，再套类别优先级。发布图片/视频/创意作品、活动/挑战赛、产品使用体验、推荐、预告不等于发布AI产品。",
        "- GPT Images创意作品、Tripo建模演示→general；Meta发起muse money challenge→bigtech；OpenAI使用模型修复漏洞→bigtech；论文/数学成果→paper；正式开源新AI模型或上线新AI应用→release。",
        "- release必须输出release_evidence：从输入逐字摘取明确的新应用/新模型/重大版本已经推出的证据，不能引用作品发布、已有工具的使用或未来预告。其他类别该字段为null。证据不足不得归release。",
        "- 短文只保留已有事实，可写短摘要，严禁为了字数补充输入没有的技术细节、讨论议题或背景。讽刺、玩笑、转述和作者判断须保持其语气与归属，不写成已证实事实。",
        "- category 与 tags 的取值只能来自上述枚举 id，禁止生成清单外内容",
        "- 没有适用取值时也必须从该维度枚举中选一个最接近的",
        "",
        "## 输出格式",
        '只输出一个 JSON 对象，无任何其他文字：'
        '{"summary": "<中文事实摘要>", "category": "<类别id>", "tags": {"<维度id>": "<取值id>"}, "release_evidence": null}',
    ]
    system = "\n".join(lines)
    user = f"标题：{title}\n媒体：{mp_name}\n\n正文：\n{content[:cfg['content_input_chars']]}"
    return system, user


# ================= 摘要校验与确定性 fallback =================

def validate_summary(tx: dict, summary) -> bool:
    cfg = enrich_cfg(tx)
    if not isinstance(summary, str):
        return False
    s = summary.strip()
    # 完整短摘要可以保留，避免为凑字数退回正文导语或额外调用。
    minimum = min(cfg["summary_min_chars"], cfg["summary_sentence_min_chars"]) if re.search(r'[。！？!?][”’"]?$', s) else cfg["summary_min_chars"]
    if not (minimum <= len(s) <= cfg["summary_max_chars"]):
        return False
    if re.search(r"^\s{0,3}#{1,6}\s", s, re.M):  # Markdown 标题
        return False
    if "](" in s or re.search(r"https?://", s):  # 链接
        return False
    if s.startswith(("- ", "* ", "• ")):  # 列表开头
        return False
    if any(marker in s for marker in SELF_REF_MARKERS):
        return False
    return True


def fit_model_summary(tx: dict, summary):
    """模型超长时仅按完整句子缩短，不再退回正文开头。"""
    if not isinstance(summary, str):
        return summary
    summary = summary.strip()
    if len(summary) > enrich_cfg(tx)["summary_max_chars"]:
        head = summary[:enrich_cfg(tx)["summary_max_chars"]]
        ends = list(re.finditer(r"[。！？!?](?:[”’\"])?", head))
        if ends:
            summary = head[:ends[-1].end()]
    return summary


def deterministic_summary(tx: dict, content: str, title: str = "") -> str:
    """模型失败时的确定性兜底：依次拼接正文段落，截断到摘要上限。

    只使用正文原文，绝不臆造；正文为空时返回空串（调用方应拒绝发布该条）。
    """
    cfg = enrich_cfg(tx)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", content or "")
                  if p.strip() and p.strip().lstrip("# ") != title.strip()
                  and not re.match(r"^(作者|编辑|来源|原创|转载声明|版权声明)[:：\s]", p.strip())]
    selected = []
    for p in paragraphs:
        if len(p) < 15 and selected:  # 过短碎片不单独成段
            continue
        selected.append(p)
        if len(" ".join(selected)) >= cfg["summary_min_chars"]:
            break
    text = " ".join(selected)
    if not text:
        return ""
    if len(text) > cfg["summary_max_chars"]:
        head = text[:cfg["summary_max_chars"]]
        ends = list(re.finditer(r"[。！？!?](?:[”’\"])?", head))
        text = head[:ends[-1].end()] if ends else head[:-1].rstrip() + "…"
    return text


def fallback_enrichment(tx: dict, content: str, title: str = "") -> dict:
    return {
        "summary": deterministic_summary(tx, content, title),
        "summaryOrigin": "source_extract",
        "classification": {"category": tx["fallbackCategoryId"], "tags": {},
                           "autoFallback": True, "autoFilled": []},
        "enrichmentStatus": "fallback",
    }


# ================= 单条加工（含重试与兜底） =================

def enrich_one(tx: dict, item: dict) -> dict:
    """item 需含 title / mpName / content_text。恒返回合法结构。

    正文缺失/过短不做标题臆造：直接返回 summary 为空的 fallback，
    由上层（build_manus_feed）判定为失败统计、不进入发布数据。
    """
    content = (item.get("content_text") or "").strip()
    brief = is_brief(item)
    if brief:
        tx = copy.deepcopy(tx)
        tx.setdefault('enrich', {}).update(summary_min_chars=4, summary_sentence_min_chars=4, summary_max_chars=60)
    cfg = enrich_cfg(tx)
    title = (item.get("title") or "").strip()
    if not content or (len(content) < 50 and not brief):
        return {"summary": "", "classification": tag_news.fallback_result(tx),
                "enrichmentStatus": "failed", "modelAttempted": False, "cacheHit": False,
                "error": {'category': 'content', 'httpStatus': None, 'systemic': False}}
    system, user = build_enrich_prompt(tx, title, item.get("mpName") or "", content)
    last_error = {'category': 'invalid_response', 'httpStatus': None, 'systemic': False}
    for attempt in range(max(1, min(2, int(cfg["max_attempts"])))):
        try:
            text = call_llm(tx, system, user + ("\n注意：只输出 JSON 对象。" if attempt else ""),
                            timeout_seconds=cfg["timeout_seconds"], operation="news_enrichment")
            raw = parse_output(text)
            # A valid summary cannot turn an invalid classification into a
            # successful model call. Keep existing per-dimension normalization.
            if isinstance(raw, dict):
                raw = enforce_event_boundary(raw, title)
                if raw.get('category') == 'release' and (not isinstance(raw.get('release_evidence'), str)
                        or len(raw['release_evidence'].strip()) < 4
                        or raw['release_evidence'].strip() not in content):
                    last_error = {'category': 'content', 'httpStatus': None, 'systemic': False}
                    continue
                raw["summary"] = fit_model_summary(tx, raw.get("summary"))
                valid_categories = {c["id"] for c in tx["categories"]}
                classification_structured = (
                    raw.get("category") in valid_categories and isinstance(raw.get("tags"), dict)
                )
                if not classification_structured:
                    last_error = {'category': 'invalid_response', 'httpStatus': None, 'systemic': False}
                    break
                classification = tag_news.validate(tx, raw)
                if brief:
                    return {'summary': source_text(item), 'summaryOrigin': 'upstream_brief',
                            'classification': classification, 'enrichmentStatus': 'complete',
                            'modelAttempted': True, 'cacheHit': False}
                if validate_summary(tx, raw.get("summary")):
                    return {"summary": raw["summary"].strip(),
                            "summaryOrigin": "model",
                            "classification": classification,
                            "enrichmentStatus": "complete", "modelAttempted": True, "cacheHit": False}
                source_summary = deterministic_summary(tx, content, title)
                if classification_structured and source_summary:
                    return {"summary": source_summary,
                            "rejectedModelSummary": raw.get("summary"),
                            "summaryOrigin": "source_extract",
                            "classification": classification,
                            "enrichmentStatus": "complete", "modelAttempted": True, "cacheHit": False}
        except Exception as exc:  # Transport errors never trigger blind paid retries.
            last_error = safe_error(exc)
            break
    return {**fallback_enrichment(tx, content, title), 'error': last_error,
            'modelAttempted': True, 'cacheHit': False}


def valid_enrichment(tx: dict, result: dict) -> bool:
    classification = result.get('classification') or {}
    return (result.get('enrichmentStatus') == 'complete' and bool(result.get('summary'))
            and isinstance(classification, dict)
            and classification.get('autoFallback') is False
            and classification.get('category') in {c['id'] for c in tx['categories']}
            and isinstance(classification.get('tags'), dict))


# ================= 缓存与批量 =================

def enrich_item_key(item: dict) -> str:
    """稳定键：账号+日期+标题哈希优先；否则退回 id/标题。"""
    raw = f"{item.get('mpName') or item.get('source') or ''}|" \
          f"{item.get('published_date') or item.get('publishedAt') or ''}|" \
          f"{(item.get('title') or '').strip().lower()}"
    return "en:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def enrich_cache_key(tx: dict, item: dict) -> str:
    """缓存键 = taxonomy/prompt/模型版本 + 稳定文章键 + 正文 SHA-256。

    正文、prompt、taxonomy 或模型任一变更都会自动失效旧结果；缓存只存加工结果。
    """
    content_sha = hashlib.sha256((item.get("content_text") or "").encode("utf-8")).hexdigest()[:16]
    suffix = ':brief-v1' if is_brief(item) else ''
    return f"{tag_news.cache_prefix(tx)}:enrich-v{ENRICH_PROMPT_VERSION}:{enrich_item_key(item)}:{content_sha}{suffix}"


def enrich_items(items: list[dict], tx: dict, cache_path: str) -> dict[str, dict]:
    """批量正文加工：缓存优先，未命中者并发调用（独立预算/并发，见 enrich 配置块）。

    返回 {enrich_item_key: result}。
    """
    cache = tag_news.load_cache(cache_path)
    cfg = enrich_cfg(tx)
    results: dict[str, dict] = {}
    todo = []
    for it in items:
        k = enrich_cache_key(tx, it)
        if isinstance(cache.get(k), dict) and valid_enrichment(tx, cache[k]):
            cached = cache[k]
            if (cached.get('classification') or {}).get('category') == 'release' and is_preview(it.get('title', '')):
                cached = {**cached, 'classification': tag_news.validate(tx, {'category': 'general', 'tags': {}})}
            results[enrich_item_key(it)] = {**cached, 'modelAttempted': False, 'cacheHit': True}
        else:
            todo.append(it)
    if todo:
        limit = max(0, int(cfg["max_new_items_per_run"]))
        selected, deferred = todo[:limit], todo[limit:]
        deadline = time.monotonic() + cfg["budget_seconds"]
        done = 0
        circuit = FailureCircuit()
        with ThreadPoolExecutor(max_workers=cfg["concurrency"]) as ex:
            queue = iter(selected)
            futs = {}

            def submit_next() -> bool:
                if circuit.stopped or time.monotonic() >= deadline:
                    return False
                try:
                    item = next(queue)
                except StopIteration:
                    return False
                futs[ex.submit(enrich_one, tx, item)] = item
                return True

            for _ in range(max(1, int(cfg["concurrency"]))):
                if not submit_next():
                    break
            while futs:
                finished, _ = wait(futs, return_when=FIRST_COMPLETED)
                for fut in finished:
                    it = futs.pop(fut)
                    r = fut.result()
                    circuit.observe({'status': 'complete' if valid_enrichment(tx, r) else 'failed',
                                     'error': r.get('error')})
                    key = enrich_cache_key(tx, it)
                    if valid_enrichment(tx, r):
                        cache[key] = r
                    else:
                        cache.pop(key, None)  # 清除旧降级缓存，下次运行可恢复。
                    results[enrich_item_key(it)] = r
                    done += 1
                    tag_news.save_cache(cache_path, cache)
                    submit_next()
        tag_news.save_cache(cache_path, cache)
        print(f"正文加工：新增 {done} 条（缓存命中 {len(items) - len(todo)} 条，"
              f"本轮上限外 {len(deferred)} 条）")
        if circuit.stopped:
            results = {key: {**value, 'batchStopped': True, 'circuitReason': circuit.reason}
                       for key, value in results.items()}
    return results


# ================= CLI =================

def selftest(tx: dict) -> int:
    ok = True

    def check(desc, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    cfg = enrich_cfg(tx)
    good_summary = "某公司宣布完成新一轮融资，资金将用于模型训练基础设施建设，并披露了估值与投资方阵容。" * 3
    check("合法摘要通过校验", validate_summary(tx, good_summary[:200]))
    check("空摘要拒绝", not validate_summary(tx, ""))
    check("超长摘要拒绝", not validate_summary(tx, "字" * (cfg["summary_max_chars"] + 1)))
    check("Markdown 标题拒绝", not validate_summary(tx, "# 标题\n" + "字" * 150))
    check("链接拒绝", not validate_summary(tx, "详见 https://example.com " + "字" * 150))
    check("模型自述拒绝", not validate_summary(tx, "作为AI，" + "字" * 150))

    content = "第一段讲了一个完整的事实，长度足够成为摘要来源，这里继续补充一些细节让它更长。\n\n第二段是补充信息。"
    s = deterministic_summary(tx, content)
    check("确定性摘要取首段", s.startswith("第一段"))
    check("确定性摘要不超上限", len(s) <= cfg["summary_max_chars"])
    check("空正文确定性摘要为空", deterministic_summary(tx, "") == "")

    fb = enrich_one(tx, {"title": "只有标题", "mpName": "测试", "content_text": ""})
    check("无正文不臆造摘要", fb["enrichmentStatus"] == "failed" and fb["summary"] == "")

    system, user = build_enrich_prompt(tx, "测试标题", "机器之心", "正文内容" * 100)
    check("正文进入 prompt", "正文内容" in user and "机器之心" in user)
    check("system 内嵌 taxonomy", all(c["id"] in system for c in tx["categories"]))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="正文加工 harness（摘要+分类+标签一次调用）")
    parser.add_argument("--taxonomy", default="config/taxonomy.json")
    parser.add_argument("--selftest", action="store_true", help="离线自检（不发请求）")
    args = parser.parse_args()
    tx = tag_news.load_taxonomy(args.taxonomy)
    if args.selftest:
        return selftest(tx)
    print("请通过 enrich_items() 编程调用，或使用 --selftest 离线自检。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
