#!/usr/bin/env python3
"""tag_news.py — 新闻打标签 harness：taxonomy 约束的 LLM 调用 + 解析 + 校验 + 缓存。

两级分类契约（详见 taxonomy.json）：
    1. 类别 6 选 1（互斥），多事件新闻按固定优先级链裁决
    2. 类别绑定维度内各单选 1 个取值，全部来自 allowlist

校验链（V4-V7）：
    V4 类别 ∈ 枚举；非法 → 重试 1 次 → 兜底 general + autoFallback 留痕
    V5 tags 只保留该类别绑定维度（越界维度丢弃）
    V6 取值 ∈ allowlist；非法/缺失 → 注入该维度 fallbackValueId + autoFilled 留痕
    V7 校验后绑定维度完备（由 V6 的注入保证）

用法:
    # 单条调试（需 DEEPSEEK_API_KEY）
    python3 scripts/tag_news.py --title "..." [--summary "..."]
    # 离线自检（不发请求，用罐头输出走校验链）
    python3 scripts/tag_news.py --selftest

纯标准库实现，Windows / Linux / macOS 均可运行。
"""
import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 公共 LLM 调用/解析能力抽取至 llm_common.py（enrich_news.py 同样复用）；
# 原名导入保持向后兼容，既有调用方与 selftest 行为不变。
from llm_common import call_llm, ensure_env_loaded, parse_output  # noqa: F401

MAX_INPUT_CHARS = 800  # 标题/摘要各自截断上限（仅轻调用；正文加工见 enrich_news.py）


# ================= 配置加载 =================

def load_taxonomy(path: str = "config/taxonomy.json") -> dict:
    # 先加载项目根 .env（设置页写入的密钥），使 build_snapshot 的 key 预检、
    # CLI 单条调试在未手动 export 时也能命中配置。
    ensure_env_loaded()
    with open(path, "r", encoding="utf-8") as f:
        tx = json.load(f)
    # 一致性自检：priority 与 categories 顺序/集合必须一致
    cat_ids = [c["id"] for c in tx["categories"]]
    if tx["priority"] != cat_ids:
        raise ValueError("taxonomy.json: priority 与 categories 顺序不一致")
    if tx["fallbackCategoryId"] not in cat_ids:
        raise ValueError("taxonomy.json: fallbackCategoryId 不在类别枚举中")
    for c in tx["categories"]:
        for d in c.get("dims", []):
            dim = tx["dimensions"][d]
            if dim["fallbackValueId"] not in {v["id"] for v in dim["values"]}:
                raise ValueError(f"taxonomy.json: 维度 {d} 的 fallbackValueId 不在取值枚举中")
    return tx


def category_map(tx: dict) -> dict:
    return {c["id"]: c for c in tx["categories"]}


# ================= 输入构造 =================

def build_prompt(tx: dict, title: str, summary: str) -> tuple[str, str]:
    """构造 (system, user) 两段 prompt。taxonomy 全量内嵌 + 优先级链 + 输出约束。"""
    lines = [
        "你是新闻分类引擎。对给定新闻执行两级分类：先判定类别（6 选 1，互斥），"
        "再在该类别绑定的维度内各选 1 个取值。",
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
        '只输出一个 JSON 对象，无任何其他文字：{"category": "<类别id>", "tags": {"<维度id>": "<取值id>"}}',
    ]
    system = "\n".join(lines)
    user = f"标题：{title[:MAX_INPUT_CHARS]}"
    if summary:
        user += f"\n摘要：{summary[:MAX_INPUT_CHARS]}"
    return system, user


# ================= API 调用与输出解析 =================
# call_llm / parse_output 已迁至 llm_common.py（顶部导入，接口不变）。


# ================= 校验链 V4-V7 =================

def fallback_result(tx: dict) -> dict:
    return {"category": tx["fallbackCategoryId"], "tags": {},
            "autoFallback": True, "autoFilled": []}


def validate(tx: dict, raw: dict | None) -> dict:
    """V4-V7 校验。恒返回合法结构：{category, tags, autoFallback, autoFilled}。"""
    if not isinstance(raw, dict):
        return fallback_result(tx)
    cat = raw.get("category")
    if isinstance(cat, str):
        cat = cat.strip()
    cats = category_map(tx)
    if cat not in cats:  # V4 类别非法 → 兜底
        return fallback_result(tx)
    tags: dict[str, str] = {}
    auto_filled: list[str] = []
    raw_tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
    for dim_id in cats[cat].get("dims", []):  # V5 越界维度天然被丢弃
        dim = tx["dimensions"][dim_id]
        valid = {v["id"] for v in dim["values"]}
        val = raw_tags.get(dim_id)
        if isinstance(val, str):
            val = val.strip()
        if val not in valid:  # V6 非法/缺失 → 注入 fallback 并留痕
            val = dim["fallbackValueId"]
            auto_filled.append(dim_id)
        tags[dim_id] = val
    # V7：绑定维度全部有值（由上方注入保证）；paper/general dims 为空 → tags 恒 {}
    return {"category": cat, "tags": tags, "autoFallback": False, "autoFilled": auto_filled}


# ================= 单条打标签（含重试与兜底） =================

def tag_one(tx: dict, item: dict) -> dict:
    """完整链路：输入校验 V1 → 调用 → 解析 → 校验链。恒返回合法结果。"""
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    if not title and not summary:  # V1 输入无效
        return fallback_result(tx)
    system, user = build_prompt(tx, title, summary)
    result = fallback_result(tx)
    for attempt in range(2):
        try:
            text = call_llm(tx, system, user + ("\n注意：只输出 JSON 对象。" if attempt else ""))
            result = validate(tx, parse_output(text))
            if not result["autoFallback"]:
                return result
        except Exception as exc:  # noqa: BLE001 - 网络/接口错误进入重试或兜底
            if attempt:
                print(f"    打标签失败（已兜底）: {exc}", file=sys.stderr)
    return result


# ================= 缓存与批量 =================

def item_key(item: dict) -> str:
    """条目稳定键：aihot 用原始 id；wechat 的 id 随签名链接变化，用 source+标题。"""
    iid = str(item.get("id") or "")
    if iid.startswith("wechat:"):
        raw = f"{item.get('source') or ''}|{(item.get('title') or '').strip().lower()}"
        return "wx:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return "id:" + iid


def cache_prefix(tx: dict) -> str:
    """缓存键前缀：taxonomy/prompt/模型 任一变更自动作废旧结果。

    LLM_MODEL 环境变量覆盖 taxonomy.model 时并入前缀，换模型自动失效。
    """
    model = os.environ.get("LLM_MODEL", "").strip() or tx["model"]["model"]
    return f"{tx['version']}:{tx['promptVersion']}:{model}"


def load_cache(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path: str, cache: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def tag_items(items: list[dict], tx: dict, cache_path: str) -> dict[str, dict]:
    """批量打标签：缓存优先，未命中者并发调用（带预算熔断）。返回 {item_key: result}。"""
    cache = load_cache(cache_path)
    prefix = cache_prefix(tx)
    results: dict[str, dict] = {}
    todo = []
    for it in items:
        k = f"{prefix}:{item_key(it)}"
        if k in cache:
            results[item_key(it)] = cache[k]
        else:
            todo.append(it)
    if todo:
        m = tx["model"]
        deadline = time.time() + m.get("budget_seconds", 120)
        done = 0
        with ThreadPoolExecutor(max_workers=m.get("concurrency", 8)) as ex:
            futs = {ex.submit(tag_one, tx, it): it for it in todo}
            for fut in as_completed(futs):
                if time.time() > deadline:
                    print("    打标签预算超时，剩余条目本轮跳过", file=sys.stderr)
                    break
                it = futs[fut]
                r = fut.result()
                cache[f"{prefix}:{item_key(it)}"] = r
                results[item_key(it)] = r
                done += 1
        save_cache(cache_path, cache)
        print(f"打标签：新增 {done} 条（缓存命中 {len(items) - len(todo)} 条）")
    return results


# ================= 展示层映射 =================

def to_display(tx: dict, result: dict) -> dict:
    """校验结果(id) → 前端展示结构(label)。"""
    cats = category_map(tx)
    cat = cats.get(result.get("category"))
    if not cat:
        return {}
    dims = []
    for dim_id, val_id in (result.get("tags") or {}).items():
        dim = tx["dimensions"].get(dim_id)
        if not dim:
            continue
        val = next((v for v in dim["values"] if v["id"] == val_id), None)
        if val:
            dims.append({"label": dim["label"], "value": val["label"]})
    return {
        "cat": cat["id"],
        "catLabel": cat["label"],
        "dims": dims,
        "autoFallback": bool(result.get("autoFallback")),
    }


# ================= CLI =================

SELFCASES = [
    # (描述, 罐头模型输出, 期望 category, 期望 tags)
    ("合法融资输出", '{"category":"financing","tags":{"industry":"ai_model","region":"cn"}}',
     "financing", {"industry": "ai_model", "region": "cn"}),
    ("类别非法→兜底", '{"category":"未知类别","tags":{}}', "general", {}),
    ("越界维度丢弃+非法取值注入", '{"category":"release","tags":{"industry":"xxx","company":"tencent"}}',
     "release", {"industry": "ai_other", "issuer": "other"}),
    ("paper 强制空 tags", '{"category":"paper","tags":{"industry":"ai_model"}}', "paper", {}),
    ("空输出→兜底", "", "general", {}),
]


def selftest(tx: dict) -> int:
    ok = True
    for desc, raw_text, want_cat, want_tags in SELFCASES:
        got = validate(tx, parse_output(raw_text))
        passed = got["category"] == want_cat and got["tags"] == want_tags
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {desc} -> {got['category']} {got['tags']}"
              + (f" autoFilled={got['autoFilled']}" if got["autoFilled"] else ""))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="新闻打标签 harness（taxonomy 约束）")
    parser.add_argument("--taxonomy", default="config/taxonomy.json")
    parser.add_argument("--title", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--selftest", action="store_true", help="离线自检（不发请求）")
    args = parser.parse_args()

    tx = load_taxonomy(args.taxonomy)
    if args.selftest:
        return selftest(tx)
    if not args.title and not args.summary:
        print("需要 --title 或 --summary（或 --selftest）", file=sys.stderr)
        return 2
    result = tag_one(tx, {"title": args.title, "summary": args.summary})
    print(json.dumps({"result": result, "display": to_display(tx, result)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
