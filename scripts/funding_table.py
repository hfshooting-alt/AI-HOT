#!/usr/bin/env python3
"""funding_table.py — 融资动态表格生成 harness。

链路：前端数据池（public/snapshot.json daily+weekly + data/manus/current.json）中
classification 为 financing 的条目 → LLM 逐篇抽取公司级融资信息（缓存优先）
→ 确定性公司归一化去重合并 → Tavily 搜索 + LLM 综合补全缺失字段（可选）
→ 原子晋升 data/funding/current.json + public/funding-table.json。

安全语义：
  - 未配置 TAVILY_API_KEY / 搜索失败：跳过补全，缺失字段留空，脚本不失败
  - 单篇抽取失败：跳过该文章并计入 stats，不中断整表
  - 输出 schema 校验失败：不覆盖上一次产物（沿用 feed 原子晋升语义）

用法:
    python scripts/funding_table.py                    # 全流程（搜索补全需 TAVILY_API_KEY）
    python scripts/funding_table.py --skip-search      # 跳过搜索补全
    python scripts/funding_table.py --no-promote       # 只生成校验，不写文件
    python scripts/funding_table.py --selftest         # 离线自检（不发请求）
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tag_news  # noqa: E402
from llm_common import call_llm, parse_output, ensure_env_loaded  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FUNDING_DEFAULTS = {
    "content_input_chars": 16000,
    "timeout_seconds": 90,
    "concurrency": 3,
    "budget_seconds": 600,
}
SEARCH_DEFAULTS = {
    "provider": "tavily",
    "api_key_env": "TAVILY_API_KEY",
    "max_results": 5,
    "cache_ttl_days": 7,
}
TABLE_SCHEMA_VERSION = 1
# 抽取 prompt 版本：字段清单/约束变更时 +1，自动作废抽取缓存
FUNDING_PROMPT_VERSION = 4

# 表格字段（company_name 为去重键，不计入）
COMPANY_FIELDS = ("product_name", "founded", "country", "industry", "team",
                  "business", "investors", "total_funding", "valuation")
# 融资专属枚举字段（仅用于构建行 dims，不进入展示列）
ENUM_FIELDS = ("industry_id", "company_type_id")
FIELD_LABELS = {
    "product_name": "产品名称",
    "founded": "公司成立时间",
    "country": "国家",
    "industry": "所属行业",
    "team": "团队情况",
    "business": "主营业务",
    "investors": "历史投资人",
    "total_funding": "累计融资金额",
    "valuation": "最新估值",
}
# 公司名归一化时剥离的常见后缀（小写匹配）
COMPANY_SUFFIXES = (
    "inc.", "inc", "ltd.", "ltd", "llc", "corp.", "corp", "corporation", "company",
    "co., ltd", "co. ltd",
    "股份有限公司", "有限责任公司", "有限公司", "集团公司", "集团", "科技公司",
    "技术有限公司", "信息技术有限公司",
)


def now_bj_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def funding_cfg(tx: dict) -> dict:
    cfg = dict(FUNDING_DEFAULTS)
    cfg.update({k: v for k, v in (tx.get("funding") or {}).items() if not k.startswith("_")})
    return cfg


def search_cfg(tx: dict) -> dict:
    cfg = dict(SEARCH_DEFAULTS)
    cfg.update({k: v for k, v in ((tx.get("funding") or {}).get("search") or {}).items()
                if not k.startswith("_")})
    return cfg


# ================= 输入装配 =================

def load_snapshot_pool(snapshot_path: Path | str) -> list[dict]:
    """snapshot.json daily+weekly sections → 按 id 去重 → 筛 financing 条目。"""
    snapshot_path = Path(snapshot_path)
    if not snapshot_path.exists():
        return []
    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    seen: dict[str, dict] = {}
    for view in (snap.get("daily"), snap.get("weekly")):
        for sec in (view or {}).get("sections") or []:
            for it in sec.get("items") or []:
                iid = it.get("id")
                if iid and iid not in seen:
                    seen[iid] = it
    return [it for it in seen.values()
            if (it.get("classification") or {}).get("cat") == "financing"]


def load_feed_pool(feed_path: Path | str) -> list[dict]:
    """data/manus/current.json → 筛 financing 条目（feed 无效时返回空）。"""
    feed_path = Path(feed_path)
    if not feed_path.exists():
        return []
    try:
        with open(feed_path, "r", encoding="utf-8") as f:
            feed = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not feed.get("ok"):
        return []
    return [it for it in feed.get("items") or []
            if (it.get("classification") or {}).get("category") == "financing"]


def dims_from_snapshot_item(item: dict) -> dict[str, str]:
    """snapshot 条目 classification.dims [{label,value}] → {label: value}。"""
    out: dict[str, str] = {}
    for d in (item.get("classification") or {}).get("dims") or []:
        if d.get("label") and d.get("value"):
            out[d["label"]] = d["value"]
    return out


def dims_from_feed_item(item: dict, tx: dict) -> dict[str, str]:
    """feed 条目 classification.tags {dimId: valueId} → {维度label: 取值label}。"""
    out: dict[str, str] = {}
    for dim_id, val_id in ((item.get("classification") or {}).get("tags") or {}).items():
        dim = tx.get("dimensions", {}).get(dim_id)
        if not dim:
            continue
        label = next((v["label"] for v in dim["values"] if v["id"] == val_id), None)
        if label:
            out[dim["label"]] = label
    return out


def build_content_index(work_dir: Path | str) -> dict[str, dict]:
    """work/manus/*/raw/content-batch-*.json 全量索引：{article_url: {title, content_text}}。"""
    work_dir = Path(work_dir)
    index: dict[str, dict] = {}
    if not work_dir.exists():
        return index
    for path in sorted(work_dir.glob("*/raw/content-batch-*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                batch = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for art in batch.get("articles") or []:
            url = art.get("article_url")
            text = (art.get("content_text") or "").strip()
            if url and text and url not in index:
                index[url] = {"title": art.get("title") or "", "content_text": text}
    return index


def to_article_record(item: dict, tx: dict, content_index: dict[str, dict],
                      is_feed: bool) -> dict:
    """统一文章记录：正文优先（work 索引命中 url 或 title），否则退回 title+summary。"""
    url = item.get("url") or ""
    entry = content_index.get(url)
    if not entry:
        title = (item.get("title") or "").strip()
        for v in content_index.values():
            if v["title"] and v["title"] == title:
                entry = v
                break
    content = (entry or {}).get("content_text") or ""
    if not content:
        parts = [item.get("title") or ""]
        if item.get("summary"):
            parts.append(item["summary"])
        content = "\n\n".join(p for p in parts if p)
    return {
        "id": item.get("id") or "",
        "title": item.get("title") or "",
        "url": url,
        "mpName": item.get("mpName") or item.get("source") or "",
        "publishedAt": item.get("publishedAt") or "",
        "dims": dims_from_feed_item(item, tx) if is_feed else dims_from_snapshot_item(item),
        "content_text": content,
    }


def load_articles(snapshot_path: Path, feed_path: Path, work_dir: Path, tx: dict) -> list[dict]:
    """快照池 + feed 池（按 id 去重，快照优先）→ 统一文章记录列表。"""
    content_index = build_content_index(work_dir)
    merged: dict[str, dict] = {}
    for it in load_snapshot_pool(snapshot_path):
        if it.get("id") and it["id"] not in merged:
            merged[it["id"]] = to_article_record(it, tx, content_index, is_feed=False)
    for it in load_feed_pool(feed_path):
        if it.get("id") and it["id"] not in merged:
            merged[it["id"]] = to_article_record(it, tx, content_index, is_feed=True)
    return list(merged.values())


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


# ================= 去重合并 =================

def normalize_company_key(name: str) -> str:
    """公司名归一化：NFKC → 去空白/括号内容 → 小写 → 循环剥离常见后缀。"""
    s = unicodedata.normalize("NFKC", name or "").strip().lower()
    s = re.sub(r"[（(【\[].*?[)）】\]]", "", s)
    s = re.sub(r"\s+", "", s).strip("·.-_ ")
    changed = True
    while changed and s:
        changed = False
        for suf in COMPANY_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)].strip("·.-_ ")
                changed = True
    return s


def company_row_id(key: str) -> str:
    return "fund:" + hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


# 国家/地区文本 → 全局 region 枚举 label 的确定性映射
_COUNTRY_REGION_KEYWORDS = {
    "中国": ["中国", "中", "中国大陆", "内地", "香港", "台湾", "澳门"],
    "美国": ["美国", "us", "usa", "美利坚合众国"],
    "欧洲": ["欧洲", "英国", "法国", "德国", "意大利", "瑞士", "瑞典", "荷兰", "西班牙", "eu"],
    "东南亚": ["东南亚", "新加坡", "泰国", "越南", "印尼", "印度尼西亚", "马来西亚", "菲律宾"],
    "日韩": ["日本", "韩国", "日韩"],
}


def _country_to_region_label(country: str | None) -> str:
    """将 LLM 抽取的国家文本映射到全局 region 枚举 label；无命中回退「其他」。"""
    if not country:
        return "其他"
    c = country.strip().lower()
    for region, keywords in _COUNTRY_REGION_KEYWORDS.items():
        if any(kw in c for kw in keywords):
            return region
    return "其他"


def _article_region_label(art: dict, country: str | None) -> str:
    """优先取源文章 dims 的 region label，缺失时用 country 文本映射。"""
    region = (art.get("dims") or {}).get("国家/地区")
    if region:
        return region
    return _country_to_region_label(country)


def merge_companies(articles: list[dict], extracts: dict[str, dict]) -> list[dict]:
    """按归一化公司名去重合并：publishedAt 降序处理，新文章字段优先、旧文章补空。"""
    companies: dict[str, dict] = {}
    for art in sorted(articles, key=lambda a: a.get("publishedAt") or "", reverse=True):
        ext = extracts.get(art["id"]) or {}
        for c in ext.get("companies") or []:
            key = normalize_company_key(c.get("company_name") or "")
            if not key:
                continue
            rid = company_row_id(key)
            rec = companies.get(rid)
            if rec is None:
                rec = {"id": rid, "company_name": c["company_name"],
                       **{f: None for f in COMPANY_FIELDS},
                       "dims": {}, "filledBySearch": [],
                       "searchSources": [], "sourceArticles": []}
                for f in COMPANY_FIELDS:
                    rec[f] = c.get(f)
                # dims 取最新文章的非空枚举值
                rec["dims"]["所属行业"] = c.get("industry_id") or "其他"
                rec["dims"]["公司类型"] = c.get("company_type_id") or "其他"
                rec["dims"]["国家/地区"] = _article_region_label(art, c.get("country"))
                companies[rid] = rec
            else:
                for f in COMPANY_FIELDS:  # 旧文章只补空
                    if rec[f] is None and c.get(f):
                        rec[f] = c[f]
                # dims 取最新非空
                if rec["dims"].get("所属行业") == "其他" and c.get("industry_id") and c["industry_id"] != "其他":
                    rec["dims"]["所属行业"] = c["industry_id"]
                if rec["dims"].get("公司类型") == "其他" and c.get("company_type_id") and c["company_type_id"] != "其他":
                    rec["dims"]["公司类型"] = c["company_type_id"]
                if rec["dims"].get("国家/地区") == "其他":
                    region = (art.get("dims") or {}).get("国家/地区")
                    if region:
                        rec["dims"]["国家/地区"] = region
                    elif c.get("country"):
                        rec["dims"]["国家/地区"] = _country_to_region_label(c["country"])
            if not any(sa.get("id") == art["id"] for sa in rec["sourceArticles"]):
                rec["sourceArticles"].append({
                    "id": art["id"], "title": art.get("title") or "",
                    "url": art.get("url") or "", "publishedAt": art.get("publishedAt") or "",
                    "mpName": art.get("mpName") or "",
                })
    rows = sorted(companies.values(),
                  key=lambda r: (r["sourceArticles"] or [{}])[0].get("publishedAt") or "",
                  reverse=True)
    for r in rows:
        r["sourceArticles"].sort(key=lambda sa: sa.get("publishedAt") or "", reverse=True)
    return rows


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


# ================= 组装与校验 =================

def assemble_table(companies: list[dict], stats: dict, generated_at: str,
                   search_note: str) -> dict:
    return {
        "schemaVersion": TABLE_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "coverageNote": "覆盖快照日报+周报池与最新 Manus feed 中的融资类新闻（约最近一周）",
        "searchNote": search_note,
        "stats": stats,
        "companies": companies,
    }


def validate_table(table: dict, tx: dict) -> None:
    """输出 schema 校验：违规抛 ValueError（调用方不晋升产物）。"""
    if table.get("schemaVersion") != TABLE_SCHEMA_VERSION:
        raise ValueError("schemaVersion 不合法")
    if not isinstance(table.get("generatedAt"), str) or not table["generatedAt"]:
        raise ValueError("generatedAt 缺失")
    dim_labels = {d["label"]: {v["label"] for v in d["values"]}
                  for d in tx.get("dimensions", {}).values()}
    # 融资专属维度并入合法集
    if tx.get("funding"):
        for dim_key in ("industry_dim", "company_type_dim"):
            dim = tx["funding"].get(dim_key)
            if dim and "label" in dim and "values" in dim:
                dim_labels[dim["label"]] = {v["label"] for v in dim["values"]}
    companies = table.get("companies")
    if not isinstance(companies, list):
        raise ValueError("companies 必须为数组")
    for rec in companies:
        if not isinstance(rec.get("id"), str) or not rec["id"].startswith("fund:"):
            raise ValueError(f"公司行 id 不合法：{rec.get('id')}")
        if not isinstance(rec.get("company_name"), str) or not rec["company_name"].strip():
            raise ValueError(f"公司行 {rec['id']} company_name 缺失")
        for f in COMPANY_FIELDS:
            v = rec.get(f)
            if v is not None and not isinstance(v, str):
                raise ValueError(f"公司行 {rec['id']} 字段 {f} 类型不合法")
        for label, value in (rec.get("dims") or {}).items():
            if label not in dim_labels or value not in dim_labels[label]:
                raise ValueError(f"公司行 {rec['id']} dims 取值不合法：{label}={value}")
        if not rec.get("sourceArticles"):
            raise ValueError(f"公司行 {rec['id']} sourceArticles 为空")
        for sa in rec["sourceArticles"]:
            if not sa.get("url"):
                raise ValueError(f"公司行 {rec['id']} 来源条目缺 url")
        for f in rec.get("filledBySearch") or []:
            if f not in COMPANY_FIELDS:
                raise ValueError(f"公司行 {rec['id']} filledBySearch 字段名不合法：{f}")


def atomic_write_json(path: Path, data: dict) -> None:
    """同目录临时文件 + os.replace 原子替换（同 build_manus_feed）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def promote_table(table: dict, data_dir: Path | str, public_dir: Path | str) -> tuple[Path, Path]:
    data_dir = Path(data_dir)
    public_dir = Path(public_dir)
    current = data_dir / "current.json"
    atomic_write_json(current, table)
    atomic_write_json(data_dir / "archive" / f"{table['generatedAt'][:10]}.json", table)
    web = public_dir / "funding-table.json"
    atomic_write_json(web, table)
    return current, web


# ================= 主流程 =================

def build_funding_table(snapshot_path: Path, feed_path: Path, work_dir: Path, tx: dict,
                        cache_dir: Path, llm_fn=call_llm, search_fn=None,
                        skip_search: bool = False, generated_at: str | None = None) -> dict:
    """从数据池生成融资表格；schema 违规抛 ValueError。search_fn=None 且未跳过时自动探测。"""
    articles = load_articles(snapshot_path, feed_path, work_dir, tx)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    extracts = extract_articles(tx, articles, cache_dir / "extraction_cache.json", llm_fn)

    companies = merge_companies(articles, extracts)
    extraction_failed = sum(1 for r in extracts.values() if r.get("status") != "complete")
    no_funding = sum(1 for r in extracts.values() if r.get("status") == "complete"
                     and not r.get("companies"))

    search_note = "已跳过搜索补全（--skip-search）"
    searched = 0
    if not skip_search:
        fn = search_fn
        if fn is None:
            fn = make_search_fn(tx)
        if fn is None:
            search_note = "未配置 TAVILY_API_KEY，缺失字段未补全"
        else:
            searched = fill_missing_fields(tx, companies, fn, llm_fn,
                                           cache_dir / "search_cache.json")
            search_note = "缺失字段已通过 Tavily 搜索补全（补全字段见 filledBySearch）"

    stats = {
        "articlesProcessed": len(articles),
        "extractionFailed": extraction_failed,
        "articlesWithoutFundingInfo": no_funding,
        "companiesTotal": len(companies),
        "companiesSearched": searched,
    }
    table = assemble_table(companies, stats, generated_at or now_bj_iso(), search_note)
    validate_table(table, tx)
    return table


# ================= 离线自检 =================

def selftest(tx: dict) -> int:
    ok = True

    def check(desc, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    check("后缀剥离归一化", normalize_company_key("宇树科技有限公司") == "宇树科技")
    check("后缀一致即合并", normalize_company_key("宇树科技有限公司")
          == normalize_company_key("宇树科技"))
    check("科技公司后缀剥离", normalize_company_key("火娃娃游戏科技公司") == "火娃娃游戏")
    check("括号内容忽略", normalize_company_key("自变量机器人（X Square Robot）")
          == normalize_company_key("自变量机器人"))
    check("大小写与后缀", normalize_company_key("X Square Robot Inc.")
          == normalize_company_key("x square robot"))
    check("空名归一化为空", normalize_company_key("") == "")

    articles = [
        {"id": "a1", "title": "新", "url": "u1", "mpName": "甲", "publishedAt": "2026-08-20",
         "dims": {"行业": "AI模型", "国家/地区": "中国"},
         "content_text": "甲公司完成B轮融资"},
        {"id": "a2", "title": "旧", "url": "u2", "mpName": "乙", "publishedAt": "2026-08-18",
         "dims": {"行业": "其他AI应用", "国家/地区": "中国"},
         "content_text": "甲公司早前完成A轮融资"},
    ]
    extracts = {
        "a1": {"status": "complete", "companies": [
            {"company_name": "甲科技", "valuation": "20亿", "country": None}]},
        "a2": {"status": "complete", "companies": [
            {"company_name": "甲科技有限公司", "valuation": None, "country": "中国"}]},
    }
    rows = merge_companies(articles, extracts)
    check("同公司合并为一行", len(rows) == 1)
    check("新文章字段优先", rows[0]["valuation"] == "20亿")
    check("旧文章补空字段", rows[0]["country"] == "中国")
    check("dims 取源文章 region", rows[0]["dims"].get("国家/地区") == "中国")
    check("dims 含所属行业", "所属行业" in rows[0]["dims"])
    check("dims 含公司类型", "公司类型" in rows[0]["dims"])
    check("来源收集齐两篇", len(rows[0]["sourceArticles"]) == 2)
    check("来源按时间倒序", rows[0]["sourceArticles"][0]["id"] == "a1")

    system, user = build_extract_prompt(tx, "标题", "公众号", "正文" * 100)
    check("字段清单进入 system", all(f in system for f in COMPANY_FIELDS))
    check("枚举字段进入 system", "industry_id" in system and "company_type_id" in system)
    check("正文进入 user", "正文" in user)

    check("非法公司记录丢弃", normalize_company_fields({"company_name": " "}) is None)
    check("字段类型归一", normalize_company_fields(
        {"company_name": "A", "founded": 2021, "country": "中国"})
        == {"company_name": "A", "founded": None, "country": "中国",
            **{f: None for f in COMPANY_FIELDS if f not in ("founded", "country")},
            "industry_id": None, "company_type_id": None})

    bad = assemble_table([], {}, "2026-08-20T00:00:00+08:00", "x")
    bad["companies"] = [{"id": "x", "company_name": ""}]
    try:
        validate_table(bad, tx)
        check("schema 校验拒绝空公司名", False)
    except ValueError:
        check("schema 校验拒绝空公司名", True)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成融资动态公司表格（funding-table.json）")
    parser.add_argument("--snapshot", default="public/snapshot.json")
    parser.add_argument("--feed", default="data/manus/current.json")
    parser.add_argument("--work-dir", default="work/manus")
    parser.add_argument("--cache-dir", default="data/funding")
    parser.add_argument("--taxonomy", default="taxonomy.json")
    parser.add_argument("--no-promote", action="store_true", help="只生成校验，不写文件")
    parser.add_argument("--skip-search", action="store_true", help="跳过 Tavily 搜索补全")
    parser.add_argument("--selftest", action="store_true", help="离线自检（不发请求）")
    parser.add_argument("--generated-at", default=None, help="覆盖生成时间（测试用）")
    args = parser.parse_args(argv)
    tx = tag_news.load_taxonomy(str(PROJECT_ROOT / args.taxonomy))
    if args.selftest:
        return selftest(tx)
    try:
        table = build_funding_table(
            PROJECT_ROOT / args.snapshot, PROJECT_ROOT / args.feed,
            PROJECT_ROOT / args.work_dir, tx, PROJECT_ROOT / args.cache_dir,
            skip_search=args.skip_search, generated_at=args.generated_at)
    except ValueError as exc:
        print(f"融资表格构建失败，保留上一次产物：{exc}", file=sys.stderr)
        return 1
    if args.no_promote:
        print(f"融资表格校验通过（--no-promote）：{table['stats']}")
        return 0
    current, web = promote_table(table, PROJECT_ROOT / "data" / "funding",
                                 PROJECT_ROOT / "public")
    print(f"已原子晋升 {current} 与 {web}：{table['stats']}；{table['searchNote']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
