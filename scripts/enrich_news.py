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
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tag_news  # noqa: E402
from llm_common import call_llm, parse_output  # noqa: E402

ENRICH_DEFAULTS = {
    "content_input_chars": 16000,
    "summary_min_chars": 100,
    "summary_max_chars": 220,
    "timeout_seconds": 90,
    "concurrency": 3,
    "budget_seconds": 900,
}
# 摘要中不允许出现的模型自述/Markdown 痕迹
SELF_REF_MARKERS = ("作为AI", "作为 AI", "作为语言模型", "我无法", "我不能")


def enrich_cfg(tx: dict) -> dict:
    cfg = dict(ENRICH_DEFAULTS)
    cfg.update({k: v for k, v in (tx.get("enrich") or {}).items() if not k.startswith("_")})
    return cfg


# ================= 输入构造 =================

def build_enrich_prompt(tx: dict, title: str, mp_name: str, content: str) -> tuple[str, str]:
    """system 内嵌 taxonomy 全量 + 摘要约束；user 携带标题/公众号名/正文（截断到上限）。"""
    cfg = enrich_cfg(tx)
    lines = [
        "你是新闻加工引擎。对给定公众号文章执行两件事：",
        f"1. 写一段 {cfg['summary_min_chars']}—{cfg['summary_max_chars']} 字的中文事实摘要；",
        "2. 执行两级分类：先判定类别（6 选 1，互斥），再在该类别绑定的维度内各选 1 个取值。",
        "",
        "## 摘要约束",
        "- 只陈述文章中的事实，不评价、不预测、不添加文章没有的信息",
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
        "- category 与 tags 的取值只能来自上述枚举 id，禁止生成清单外内容",
        "- 没有适用取值时也必须从该维度枚举中选一个最接近的",
        "",
        "## 输出格式",
        '只输出一个 JSON 对象，无任何其他文字：'
        '{"summary": "<中文事实摘要>", "category": "<类别id>", "tags": {"<维度id>": "<取值id>"}}',
    ]
    system = "\n".join(lines)
    user = f"标题：{title}\n公众号：{mp_name}\n\n正文：\n{content[:cfg['content_input_chars']]}"
    return system, user


# ================= 摘要校验与确定性 fallback =================

def validate_summary(tx: dict, summary) -> bool:
    cfg = enrich_cfg(tx)
    if not isinstance(summary, str):
        return False
    s = summary.strip()
    if not (cfg["summary_min_chars"] <= len(s) <= cfg["summary_max_chars"]):
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


def deterministic_summary(tx: dict, content: str) -> str:
    """模型失败时的确定性兜底：取正文首个有效段落，截断到摘要上限。

    只使用正文原文，绝不臆造；正文为空时返回空串（调用方应拒绝发布该条）。
    """
    cfg = enrich_cfg(tx)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", content or "") if p.strip()]
    text = ""
    for p in paragraphs:
        if len(p) < 15 and text:  # 过短碎片不单独成段
            continue
        text = p
        break
    if not text:
        return ""
    if len(text) > cfg["summary_max_chars"]:
        text = text[:cfg["summary_max_chars"]]
    return text


def fallback_enrichment(tx: dict, content: str) -> dict:
    return {
        "summary": deterministic_summary(tx, content),
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
    cfg = enrich_cfg(tx)
    title = (item.get("title") or "").strip()
    if not content or len(content) < 50:
        return {"summary": "", "classification": tag_news.fallback_result(tx),
                "enrichmentStatus": "failed"}
    system, user = build_enrich_prompt(tx, title, item.get("mpName") or "", content)
    for attempt in range(2):
        try:
            text = call_llm(tx, system, user + ("\n注意：只输出 JSON 对象。" if attempt else ""),
                            timeout_seconds=cfg["timeout_seconds"])
            raw = parse_output(text)
            # 重试条件：不可解析或摘要不合法。分类/标签交给 tag_news.validate() 的
            # 既有兜底机制（非法类别→general+autoFallback 留痕；非法取值→注入 fallback）。
            if isinstance(raw, dict) and validate_summary(tx, raw.get("summary")):
                cls = tag_news.validate(tx, raw)
                return {"summary": raw["summary"].strip(), "classification": cls,
                        "enrichmentStatus": "complete"}
        except Exception as exc:  # noqa: BLE001 - 网络/接口错误进入重试或兜底
            if attempt:
                print(f"    正文加工失败（已兜底）: {exc}", file=sys.stderr)
    return fallback_enrichment(tx, content)


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
    return f"{tag_news.cache_prefix(tx)}:{enrich_item_key(item)}:{content_sha}"


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
        if k in cache:
            results[enrich_item_key(it)] = cache[k]
        else:
            todo.append(it)
    if todo:
        deadline = time.time() + cfg["budget_seconds"]
        done = 0
        with ThreadPoolExecutor(max_workers=cfg["concurrency"]) as ex:
            futs = {ex.submit(enrich_one, tx, it): it for it in todo}
            for fut in as_completed(futs):
                if time.time() > deadline:
                    print("    正文加工预算超时，剩余条目本轮跳过", file=sys.stderr)
                    break
                it = futs[fut]
                r = fut.result()
                cache[enrich_cache_key(tx, it)] = r
                results[enrich_item_key(it)] = r
                done += 1
        tag_news.save_cache(cache_path, cache)
        print(f"正文加工：新增 {done} 条（缓存命中 {len(items) - len(todo)} 条）")
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
