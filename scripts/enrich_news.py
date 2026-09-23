#!/usr/bin/env python3
"""enrich_news.py — 正文加工 harness：一次模型调用同时产出 摘要 + 分类 + 标签。

精选复用 tag_news 的 taxonomy 校验和版本化缓存；全部文章使用独立通用分类提示词。
与 tag_news.py 的边界：
  - tag_news：保留 taxonomy 加载、展示与历史轻量分类兼容工具
  - enrich_news：正文上限 enrich.content_input_chars（默认 16,000 字符）的重调用
    （经脚本验证的 Manus 正文），预算/并发/超时走 taxonomy.json 的 enrich 配置块
  - 分类独立于精选；缺正文不凭标题打标，非精选不强制生成 AI 行业维度

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
ENRICH_PROMPT_VERSION = 5
LIBRARY_PROMPT_VERSION = 2
# 摘要中不允许出现的模型自述/Markdown 痕迹
SELF_REF_MARKERS = ("作为AI", "作为 AI", "作为语言模型", "我无法", "我不能")


def is_preview(title):
    return bool(re.search(r'预告|前瞻(?!性)|预热', title) and not re.search(r'已正式发布|现已上线', title))


def event_boundary_reason(category, title):
    if category != 'release':
        return None
    # Only observed roundup column labels, not arbitrary titles containing 早.
    # A genuine launch inside a multi-event bulletin does not classify the
    # whole bulletin as a release. Apply this projection to fresh and cached
    # results alike, while retaining the original model/cache response.
    if (re.search(r'[|｜]\s*极客早知道\s*$', title)
            or re.fullmatch(r'\s*华尔街见闻早餐FM(?:-Radio)?(?:\s*[|｜]\s*\d{4}年\d{1,2}月\d{1,2}日)?\s*', title)):
        return 'roundup_not_release'
    if is_preview(title):
        return 'preview_not_release'
    # A sales record alone reports an existing product's performance. Keep
    # titles that also indicate an actual new product/version launch untouched.
    launch = re.search(r'新作|新品|新游|新产品|新版本|重大版本|发布|上线|发售|推出', title)
    milestone = re.search(r'(?:销量|售出|卖出)\s*(?:已|累计|正式|首次|再度|再|已累计)*\s*'
                          r'(?:突破|达到|超过|超越|超|破)\s*[0-9０-９一二三四五六七八九十百千万亿两]+', title)
    if milestone and not launch:
        return 'sales_milestone_not_release'
    return None


def enforce_event_boundary(raw, title):
    """Explicit roundups, previews and sales-only milestones are not releases."""
    if event_boundary_reason(raw.get('category'), title):
        return {**raw, 'category': 'general', 'tags': {}, 'release_evidence': None}
    return raw


def release_evidence_match(quote: str, content: str) -> str | None:
    """Match one contiguous excerpt, allowing Unicode whitespace differences only.

    Punctuation, words, character order and intervening non-whitespace text
    remain significant. This never joins separated excerpts across omitted text.
    """
    quote = quote.strip()
    if not quote:
        return None
    if quote in content:
        return 'exact'
    compact_quote = ''.join(character for character in quote if not character.isspace())
    compact_content = ''.join(character for character in content if not character.isspace())
    if compact_quote and compact_quote in compact_content:
        return 'whitespace_normalized'
    return None


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
        "- release_evidence只复制正文中的一段连续原话。一句即可；不能改写、拼接不同句段、删去中间文字或替换标点。不用概括句充当引文。综合晨报按general；企业战略或转型分析不因顺带提及新品而归release。",
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


def build_library_prompt(tx: dict, title: str, mp_name: str, content: str) -> tuple[str, str]:
    """Independent, topic-neutral classification; the selected v4 prompt stays unchanged."""
    cfg = enrich_cfg(tx)
    system = '\n'.join([
        '你是新闻加工引擎，根据所给正文写中文事实摘要，并给文章分类。是否进入投资精选由另一独立步骤决定。',
        f"摘要通常为 {cfg['summary_min_chars']}—{cfg['summary_max_chars']} 字，以完整句子结束；短文只保留已有事实，不为字数补充背景。",
        '忠实概括文章主事件或回顾主线，保留时间、观点归属与不确定性。汇编需概括主要内容，不只摘开头。',
        '文章可涉及任何行业，不强行寻找或编造 AI 主线。不得把黄金、家电、电商等普通内容改写为 AI 新闻。',
        '不得使用 Markdown、链接、列表或模型自述；不重复标题、作者和版权声明。',
        '按文章主事件依次判定六个互斥类别：',
        'financing：本轮新增融资、并购或上市事件；只讨论资本市场、行业趋势或回顾旧融资不算新增融资。',
        'release：新产品、新模型或重大版本已经正式推出。使用体验、对比、推荐、修复漏洞、作品、活动或未来预告不算新品发布。',
        'bigtech：大型科技企业本轮战略、组织、经营等动态，且主事件不属于前述类别。',
        'paper：研究论文或科研成果。',
        'interview：以采访、人物访谈或人物回顾为主。',
        'general：其余新闻、行业分析、评论、使用体验及综合回顾。',
        '本步骤不判 AI 行业维度，tags 必须是空对象 {}，不得自动填“其他AI应用”。',
        'release 必须提供 release_evidence，从输入正文逐字摘取至少4字的已正式推出证据；其他类别该字段为 null。证据不足不得归 release。',
        '引文只需一段连续原话，不能拼接、改写、省略中间文字或替换标点。综合晨报按general，战略分析不因顺带提及新品而归release。',
        '只输出 JSON 对象：{"summary":"中文事实摘要","category":"六类之一","tags":{},"release_evidence":null}',
    ])
    return system, f"标题：{title}\n媒体：{mp_name}\n\n正文：\n{content[:cfg['content_input_chars']]}"


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


# ================= 单条加工（一次请求与确定性兜底） =================

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
    library = cfg.get('article_scope') == 'all_articles'
    prompt = build_library_prompt if library else build_enrich_prompt
    system, user = prompt(tx, title, item.get("mpName") or "", content)
    diagnostic = {}
    last_error = {'category': 'invalid_response', 'httpStatus': None, 'systemic': False}

    def finish(result, reason=None):
        if reason:
            diagnostic['validationReason'] = reason
        return {**result, 'modelAttempted': True, 'cacheHit': False,
                'privateReview': copy.deepcopy(diagnostic)}

    # One request only. Explicit recovery, rather than an internal retry, owns
    # any later attempt at a failed article.
    try:
        text = call_llm(tx, system, user, timeout_seconds=cfg["timeout_seconds"], operation="news_enrichment")
        diagnostic['modelResponse'] = text
        raw = parse_output(text)
        if not isinstance(raw, dict):
            diagnostic['validationReason'] = 'response_invalid_json_object'
        else:
            boundary_reason = event_boundary_reason(raw.get('category'), title)
            if boundary_reason:
                diagnostic['classificationBoundary'] = {'reason': boundary_reason, 'from': 'release', 'to': 'general'}
            raw = enforce_event_boundary(raw, title)
            release_reason = None
            if raw.get('category') == 'release':
                quote = raw.get('release_evidence')
                if quote is None:
                    release_reason = 'release_evidence_missing'
                elif not isinstance(quote, str):
                    release_reason = 'release_evidence_not_string'
                elif len(quote.strip()) < 4:
                    release_reason = 'release_evidence_too_short'
                else:
                    match = release_evidence_match(quote, content)
                    diagnostic['evidenceMatch'] = match or 'not_found'
                    if match is None:
                        release_reason = 'release_evidence_not_in_source'
            if release_reason:
                last_error = {'category': 'content', 'httpStatus': None, 'systemic': False}
                diagnostic['validationReason'] = release_reason
            elif (raw.get('category') not in {c['id'] for c in tx['categories']}
                    or not isinstance(raw.get('tags'), dict)):
                diagnostic['validationReason'] = 'classification_structure_invalid'
            else:
                # Library-only classification must not invent an AI industry.
                # Selected articles retain the existing full taxonomy validator.
                classification = ({'category': raw['category'], 'tags': {},
                                   'autoFallback': False, 'autoFilled': []}
                                  if library else tag_news.validate(tx, raw))
                raw_summary = fit_model_summary(tx, raw.get('summary'))
                base = {'classification': classification, 'classificationStatus': 'complete'}
                if brief:
                    return finish({**base, 'summary': source_text(item), 'summaryOrigin': 'upstream_brief',
                                   'summaryStatus': 'complete', 'enrichmentStatus': 'complete'})
                if validate_summary(tx, raw_summary):
                    return finish({**base, 'summary': raw_summary.strip(), 'summaryOrigin': 'model',
                                   'summaryStatus': 'complete', 'enrichmentStatus': 'complete'})
                source_summary = deterministic_summary(tx, content, title)
                if source_summary:
                    return finish({**base, 'summary': source_summary, 'summaryOrigin': 'source_extract',
                                   'summaryStatus': 'complete', 'enrichmentStatus': 'complete',
                                   'rejectedModelSummary': raw.get('summary')}, 'summary_replaced_with_source_excerpt')
                return finish({**base, 'summary': '', 'summaryStatus': 'failed', 'enrichmentStatus': 'partial',
                               'error': {'category': 'content', 'httpStatus': None, 'systemic': False}},
                              'summary_invalid_no_source_excerpt')
    except Exception as exc:
        last_error = safe_error(exc)
        diagnostic['validationReason'] = ('response_invalid_json' if isinstance(exc, json.JSONDecodeError)
                                          else 'request_or_response_error')
    fallback = fallback_enrichment(tx, content, title)
    return finish({**fallback, 'classificationStatus': 'failed',
                   'summaryStatus': 'complete' if fallback['summary'] else 'failed', 'error': last_error})


def valid_classification(tx: dict, result: dict) -> bool:
    classification = result.get('classification')
    return (isinstance(classification, dict) and classification.get('autoFallback') is False
            and classification.get('category') in {c['id'] for c in tx['categories']}
            and isinstance(classification.get('tags'), dict))


def cacheable_enrichment(tx: dict, result: dict) -> bool:
    return (valid_enrichment(tx, result) or (result.get('enrichmentStatus') == 'partial'
            and result.get('summaryStatus') == 'failed' and valid_classification(tx, result)))


def cache_result(result: dict) -> dict:
    # Raw responses/quotes belong only in the private inputs review, never in
    # the published data/cache tree or article-library projection.
    return {k: copy.deepcopy(v) for k, v in result.items()
            if k not in ('privateReview', 'rejectedModelSummary', 'processingCacheKey', 'processingPrompt')}


def valid_enrichment(tx: dict, result: dict) -> bool:
    return (result.get('enrichmentStatus') == 'complete' and bool(result.get('summary'))
            and valid_classification(tx, result))


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
    if enrich_cfg(tx).get('article_scope') == 'all_articles':
        suffix += f':library-v{LIBRARY_PROMPT_VERSION}'
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
        if cfg.get('article_scope') == 'all_articles':
            legacy_tx = copy.deepcopy(tx)
            legacy_tx.setdefault('enrich', {}).pop('article_scope', None)
            legacy_key = enrich_cache_key(legacy_tx, it)
            if isinstance(cache.get(legacy_key), dict) and valid_enrichment(legacy_tx, cache[legacy_key]):
                k = legacy_key
        if isinstance(cache.get(k), dict) and cacheable_enrichment(tx, cache[k]):
            cached = cache_result(cache[k])
            boundary_reason = event_boundary_reason((cached.get('classification') or {}).get('category'), it.get('title', ''))
            if boundary_reason:
                classification = ({'category': 'general', 'tags': {}, 'autoFallback': False, 'autoFilled': []}
                    if cfg.get('article_scope') == 'all_articles' else tag_news.validate(tx, {'category': 'general', 'tags': {}}))
                cached = {**cached, 'classification': classification, 'privateReview': {
                    'classificationBoundary': {'reason': boundary_reason, 'from': 'release', 'to': 'general'}}}
            results[enrich_item_key(it)] = {**cached, 'modelAttempted': False, 'cacheHit': True,
                'processingCacheKey': k, 'processingPrompt': (f'library-v{LIBRARY_PROMPT_VERSION}'
                    if k.endswith(f':library-v{LIBRARY_PROMPT_VERSION}') else f'selected-v{ENRICH_PROMPT_VERSION}')}
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
                    if cacheable_enrichment(tx, r):
                        cache[key] = cache_result(r)
                    else:
                        cache.pop(key, None)  # 清除旧降级缓存，下次运行可恢复。
                    results[enrich_item_key(it)] = {**r, 'processingCacheKey': key,
                        'processingPrompt': (f'library-v{LIBRARY_PROMPT_VERSION}'
                            if cfg.get('article_scope') == 'all_articles' else f'selected-v{ENRICH_PROMPT_VERSION}')}
                    done += 1
                    tag_news.save_cache(cache_path, cache)
                    submit_next()
        tag_news.save_cache(cache_path, cache)
        print(f"正文加工：新增 {done} 条（缓存命中 {len(items) - len(todo)} 条，"
              f"本轮上限外 {len(deferred)} 条）")
        if circuit.stopped:
            results = {key: {**value, 'batchStopped': True, 'circuitReason': circuit.reason}
                       for key, value in results.items()}
    # Reviewed summaries are a publication projection, applied only after all
    # model cache writes. Never relabel the original cached model response.
    from news_editorial_reviews import apply_summary_review
    for item in items:
        key = enrich_item_key(item)
        if key in results:
            results[key] = apply_summary_review(item, results[key])
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
