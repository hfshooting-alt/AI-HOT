"""融资流水线：extraction。"""
import hashlib
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import tag_news
from llm_common import call_llm, parse_output
from .config import funding_cfg, COMPANY_FIELDS, FIELD_LABELS, ENUM_FIELDS, FUNDING_PROMPT_VERSION


# ================= LLM 抽取 =================

def _dim_id_label_pairs(tx: dict, dim_path: tuple[str, str]) -> list[str]:
    """从 taxonomy 读取维度下所有取值的 id(label) 列表（用于 prompt 白名单）。"""
    node = tx
    for key in dim_path:
        node = (node or {}).get(key, {})
    return [f"{v['id']}({v['label']})" for v in node.get("values", [])]


def _dim_id_label_map(tx: dict, dim_path: tuple[str, str]) -> dict[str, str]:
    """从 taxonomy 读取维度下 id → label 映射。"""
    node = tx
    for key in dim_path:
        node = (node or {}).get(key, {})
    return {v["id"]: v["label"] for v in node.get("values", [])}


def build_extract_prompt(tx: dict, title: str, source_name: str,
                         content: str) -> tuple[str, str]:
    cfg = funding_cfg(tx)
    industry_labels = _dim_id_label_pairs(tx, ("funding", "industry_dim"))
    company_type_labels = _dim_id_label_pairs(tx, ("funding", "company_type_dim"))
    lines = [
        "你是融资信息抽取引擎。从给定新闻中抽取所有涉及融资、投资、估值变动的公司信息。",
        "",
        "## 输出字段（每家公司一条记录，字段值一律为字符串或 null）",
        "- company_name：公司名称（必填，以文中原文名称为准）",
    ]
    for f in COMPANY_FIELDS:
        lines.append(f"- {f}（{FIELD_LABELS[f]}）：文中明确提及则填写，否则为 null")
    lines += [
        "- industry_id：所属行业枚举 id，只能从以下白名单取值：" + " / ".join(industry_labels),
        "- company_type_id：公司类型枚举 id，只能从以下白名单取值：" + " / ".join(company_type_labels),
        "",
        "## 判定口径",
        "- 所属行业依据公司当前核心产品/业务的泛娱乐/AI 方向判定：",
        "  · AI游戏：AI 驱动的游戏、玩法、游戏内容或游戏平台；",
        "  · AI社交/陪伴：AI 聊天、虚拟伴侣、AI 社交应用；",
        "  · AI互动内容/娱乐：AI 互动剧、互动内容、娱乐社区；",
        "  · AI创作工具/生产力：AI 写作、绘画、音视频、代码等创作/生产力工具；",
        "  · AI模型/基础设施：基础模型、模型平台、AI 基础设施、算力服务；",
        "  · 具身智能/机器人：机器人、具身智能、智能硬件；",
        "  · 其他：无法归入以上细分类别时取其他。",
        "- 公司类型依据融资阶段与商业地位判定：早期/天使/A/B 轮、未上市创业团队取初创公司；已上市、头部平台、巨头子公司或成熟并购标的大厂/已上市；无法判定取其他。",
        "",
        "## 约束",
        "- 只陈述文中明确提到的事实，缺失字段一律输出 null，禁止臆造、推测或用常识填充",
        "- 金额、估值、时间保留原文表述（如“近3亿美元”“投后估值20亿美元”“2021年”）",
        "- 团队情况概括创始团队背景（如“创始人来自华为，核心团队十余年华为经验”）",
        "- 历史投资人列出文中提及的投资方；主营业务一句话概括",
        "- 新闻不涉及具体公司的融资/投资/估值信息时，companies 返回空数组",
        "- 一篇文章提到多家公司时全部抽取",
        "- industry_id / company_type_id 必须从白名单取值；无法判定时取 other，禁止编造不在白名单的值",
        "",
        "## 输出格式",
        '只输出一个 JSON 对象，无任何其他文字：'
        '{"has_funding_info": true, "companies": ['
        '{"company_name": "...", "product_name": null, "founded": null, "country": null, '
        '"industry": null, "industry_id": "other", "team": null, "business": null, '
        '"investors": null, "total_funding": null, "valuation": null, '
        '"company_type_id": "other"}]}',
    ]
    system = "\n".join(lines)
    user = (f"标题：{title}\n来源：{source_name}\n\n正文：\n"
            f"{content[:cfg['content_input_chars']]}")
    return system, user


def _normalize_enum_id(raw_id: str | None, tx: dict, dim_path: tuple[str, str]) -> str:
    """校验枚举 id 是否在白名单内，缺失/非法时回退 fallbackValueId 对应的 label。"""
    node = tx
    for key in dim_path:
        node = (node or {}).get(key, {})
    id_to_label = {v["id"]: v["label"] for v in node.get("values", [])}
    if raw_id in id_to_label:
        return id_to_label[raw_id]
    fallback = node.get("fallbackValueId")
    if fallback and fallback in id_to_label:
        return id_to_label[fallback]
    # 极端兜底：taxonomy 不完整时仍返回可读 label
    return "其他"


def normalize_company_fields(raw: dict, tx: dict | None = None) -> dict | None:
    """LLM 单条公司记录 → 合法结构；非对象/company_name 缺失或为空返回 None。"""
    if not isinstance(raw, dict):
        return None
    name = raw.get("company_name")
    if not isinstance(name, str) or not name.strip():
        return None
    out = {"company_name": name.strip()}
    for f in COMPANY_FIELDS:
        v = raw.get(f)
        out[f] = v.strip() if isinstance(v, str) and v.strip() else None
    # 融资专属枚举字段：仅作为 dims 来源，校验失败回退其他，不丢弃公司行
    if tx is not None:
        out["industry_id"] = _normalize_enum_id(raw.get("industry_id"), tx, ("funding", "industry_dim"))
        out["company_type_id"] = _normalize_enum_id(raw.get("company_type_id"), tx, ("funding", "company_type_dim"))
    else:
        # 未提供 tx 时保持旧行为：仅保留字符串，不校验
        for f in ENUM_FIELDS:
            v = raw.get(f)
            out[f] = v.strip() if isinstance(v, str) and v.strip() else None
    return out


def extract_one(tx: dict, article: dict, llm_fn=call_llm) -> dict:
    """单篇抽取（含 1 次重试）。恒返回 {"status", "companies"}。"""
    cfg = funding_cfg(tx)
    content = (article.get("content_text") or "").strip()
    if not content or len(content) < 50:
        return {"status": "failed", "companies": []}
    system, user = build_extract_prompt(tx, article.get("title") or "",
                                        article.get("mpName") or "", content)
    for attempt in range(2):
        try:
            text = llm_fn(tx, system, user + ("\n注意：只输出 JSON 对象。" if attempt else ""),
                          timeout_seconds=cfg["timeout_seconds"])
            raw = parse_output(text)
            if isinstance(raw, dict) and isinstance(raw.get("companies"), list):
                companies = [c for c in (normalize_company_fields(x, tx) for x in raw["companies"])
                             if c]
                return {"status": "complete", "companies": companies}
        except Exception:  # noqa: BLE001 - 网络/接口错误进入重试
            pass
    return {"status": "failed", "companies": []}


def article_cache_key(tx: dict, article: dict) -> str:
    """缓存键 = taxonomy/prompt/模型版本 + funding prompt 版本 + 文章 id + 内容 sha。"""
    content_sha = hashlib.sha256(
        (article.get("content_text") or "").encode("utf-8")).hexdigest()[:16]
    return (f"{tag_news.cache_prefix(tx)}:fpv{FUNDING_PROMPT_VERSION}"
            f":{article.get('id') or hashlib.md5(article.get('title', '').encode()).hexdigest()[:16]}"
            f":{content_sha}")


def extract_articles(tx: dict, articles: list[dict], cache_path: Path | str,
                     llm_fn=call_llm) -> dict[str, dict]:
    """批量抽取：缓存优先，未命中者并发调用（预算熔断）。返回 {article_id: result}。"""
    cfg = funding_cfg(tx)
    cache_path = Path(cache_path)
    cache = tag_news.load_cache(str(cache_path))
    results: dict[str, dict] = {}
    todo = []
    for art in articles:
        k = article_cache_key(tx, art)
        if k in cache:
            results[art["id"]] = cache[k]
        else:
            todo.append(art)
    if todo:
        deadline = time.time() + cfg["budget_seconds"]
        done = 0
        with ThreadPoolExecutor(max_workers=cfg["concurrency"]) as ex:
            futs = {ex.submit(extract_one, tx, a, llm_fn): a for a in todo}
            for fut in as_completed(futs):
                if time.time() > deadline:
                    print("    融资抽取预算超时，剩余文章本轮跳过", file=sys.stderr)
                    break
                art = futs[fut]
                r = fut.result()
                # 失败结果不进缓存：下次运行（如配置好 key 后）自动重试
                if r.get("status") == "complete":
                    cache[article_cache_key(tx, art)] = r
                results[art["id"]] = r
                done += 1
        tag_news.save_cache(str(cache_path), cache)
        print(f"融资抽取：新增 {done} 篇（缓存命中 {len(articles) - len(todo)} 篇）")
    return results
