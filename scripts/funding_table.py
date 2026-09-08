#!/usr/bin/env python3
"""funding_table.py — 融资动态表格生成 harness。

链路：前端数据池（web/public/snapshot.json daily+weekly + data/manus/current.json）中
classification 为 financing 的条目 → LLM 逐篇抽取公司级融资信息（缓存优先）
→ 确定性公司归一化去重合并 → Tavily 搜索 + LLM 综合补全缺失字段（可选）
→ 原子晋升 data/funding/current.json + web/public/funding-table.json。

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tag_news
from llm_common import call_llm

# 保留原模块导入接口；实现按流水线阶段拆分。
from funding.config import (
    FUNDING_DEFAULTS,
    SEARCH_DEFAULTS,
    TABLE_SCHEMA_VERSION,
    FUNDING_PROMPT_VERSION,
    COMPANY_FIELDS,
    ENUM_FIELDS,
    FIELD_LABELS,
    COMPANY_SUFFIXES,
    now_bj_iso,
    funding_cfg,
    search_cfg,
)

from funding.inputs import (
    load_snapshot_pool,
    load_feed_pool,
    dims_from_snapshot_item,
    dims_from_feed_item,
    build_content_index,
    to_article_record,
    load_articles,
)

from funding.extraction import (
    _dim_id_label_pairs,
    _dim_id_label_map,
    build_extract_prompt,
    _normalize_enum_id,
    normalize_company_fields,
    extract_one,
    article_cache_key,
    extract_articles,
)

from funding.companies import (
    normalize_company_key,
    company_row_id,
    _COUNTRY_REGION_KEYWORDS,
    _country_to_region_label,
    _article_region_label,
    merge_companies,
)

from funding.search import (
    tavily_search,
    build_search_prompt,
    apply_search_fill,
    fill_missing_fields,
    make_search_fn,
)

from funding.output import (
    assemble_table,
    validate_table,
    atomic_write_json,
    promote_table,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
    extraction_failed = len(articles) - sum(
        1 for art in articles if (extracts.get(art["id"]) or {}).get("status") == "complete")
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
    parser.add_argument("--snapshot", default="web/public/snapshot.json")
    parser.add_argument("--feed", default="data/manus/current.json")
    parser.add_argument("--work-dir", default="work/manus")
    parser.add_argument("--cache-dir", default="data/funding")
    parser.add_argument("--data-dir", default="data/funding")
    parser.add_argument("--public-dir", default="web/public")
    parser.add_argument("--taxonomy", default="config/taxonomy.json")
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
    current, web = promote_table(table, PROJECT_ROOT / args.data_dir,
                                 PROJECT_ROOT / args.public_dir)
    print(f"已原子晋升 {current} 与 {web}：{table['stats']}；{table['searchNote']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
