#!/usr/bin/env python3
"""build_manus_feed.py — 生成可原子发布的 Manus 规范化 feed（data/manus/current.json）。

链路：已校验的三组发现结果 + 已校验正文批次 → enrich_news 正文加工
→ §2.4 规范化 item → contracts.validate_feed 全量校验 → 临时文件 + os.replace 原子晋升。

安全语义：
  - 三组发现结果缺一或不合法：不覆盖上一次 current.json，只在 state.json 记录失败
  - 三组全部 complete 但当天无文章：生成合法空 items 文件并 ok=true（不是采集失败）
  - 来源级失败：degraded=true，成功文章照常发布
  - 全文与 Secret 一律不落盘：feed 只含正文哈希、摘要和加工结果

用法:
    python scripts/build_manus_feed.py --date 2026-08-16
    python scripts/build_manus_feed.py --date 2026-08-16 --no-promote   # 只生成不晋升
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich_news  # noqa: E402
import tag_news  # noqa: E402
from manus_source import contracts  # noqa: E402
from manus_source.config import load_sources  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("group_a", "group_b", "group_c")


def now_bj_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


# ================= 输入装载 =================

def load_discoveries(raw_dir: Path, target_date: str, groups_cfg: dict) -> dict[str, dict]:
    """读取并校验三组发现原始结果；缺组/损坏/契约违规一律抛 ContractError。"""
    discoveries = {}
    for group in GROUPS:
        path = Path(raw_dir) / f"discovery-{group}.json"
        if not path.exists():
            raise contracts.ContractError(f"缺少发现结果文件：{path.name}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError as exc:
            raise contracts.ContractError(f"{path.name} 不是合法 JSON：{exc}") from exc
        accounts = [s["account_name"] for s in groups_cfg[group]]
        contracts.validate_discovery(payload, group, target_date, accounts)
        discoveries[group] = payload
    return discoveries


def load_content_articles(raw_dir: Path, target_date: str,
                          expected_titles: dict[str, str],
                          min_content_chars: int) -> tuple[list[dict], list[dict]]:
    """汇总所有正文批次原始文件并通过本地门槛；损坏批次抛 ContractError（不静默跳过）。"""
    ok_all: list[dict] = []
    failed_all: list[dict] = []
    paths = sorted(Path(raw_dir).glob("content-batch-*.json"))
    if not paths:
        raise contracts.ContractError("缺少正文批次文件（content-batch-*.json）")
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                batch = json.load(f)
        except json.JSONDecodeError as exc:
            raise contracts.ContractError(f"{path.name} 不是合法 JSON：{exc}") from exc
        ok, failed = contracts.validate_content_batch(batch, target_date, expected_titles,
                                                      min_content_chars)
        ok_all.extend(ok)
        failed_all.extend(failed)
    # 重试批次可能包含同一 URL；成功结果优先，旧失败不再重复计数。
    by_url = {a["article_url"]: a for a in ok_all}
    failed_by_url = {a["article_url"]: a for a in failed_all if a["article_url"] not in by_url}
    return list(by_url.values()), list(failed_by_url.values())


# ================= 规范化 item =================

def make_items(ok_articles: list[dict], enrich_results: dict[str, dict]) -> tuple[list[dict], int, int]:
    """正文 + 加工结果 → §2.4 规范化 item。返回 (items, fallback 数, 因加工失败丢弃数)。"""
    items: list[dict] = []
    fallback = 0
    dropped = 0
    for art in ok_articles:
        key = enrich_news.enrich_item_key({
            "mpName": art["account_name"], "title": art["title"],
            "published_date": art["published_date"]})
        enr = enrich_results.get(key)
        if not enr or enr.get("enrichmentStatus") == "failed" or not enr.get("summary"):
            dropped += 1  # 无合格摘要：不发布、不臆造，只计入失败统计
            continue
        if enr["enrichmentStatus"] == "fallback":
            fallback += 1
        items.append({
            "id": contracts.stable_article_id(art["account_name"], art["published_date"],
                                              art["title"]),
            "title": art["title"],
            "summary": enr["summary"],
            "url": art["article_url"],
            "source": f"公众号：{art['account_name']}",
            "sourceType": "wechat",
            "collector": "manus",
            "mpName": art["account_name"],
            "sourcePlatform": art.get("source_platform"),
            "author": art.get("author"),
            "publishedAt": f"{art['published_date']}T12:00:00+08:00",
            "publishedPrecision": "date",
            "contentSha256": contracts.content_sha256(art.get("content_text") or ""),
            "enrichmentStatus": enr["enrichmentStatus"],
            "classification": enr["classification"],
        })
    return items, fallback, dropped


def assemble_feed(target_date: str, discoveries: dict[str, dict], items: list[dict],
                  fallback_count: int, generated_at: str) -> dict:
    audits = [a for g in GROUPS for a in discoveries[g]["source_audits"]]
    discovered = sum(1 for g in GROUPS
                     for a in discoveries[g]["articles"] if a["extraction_status"] == "complete")
    failed_accounts = sum(1 for a in audits if a["source_status"] == "failed")
    return {
        "schemaVersion": contracts.FEED_SCHEMA_VERSION,
        "targetDate": target_date,
        "generatedAt": generated_at,
        "collector": "manus",
        "ok": True,
        "degraded": failed_accounts > 0,
        "stats": {
            "configuredAccounts": len(audits),
            "completeAccounts": len(audits) - failed_accounts,
            "failedAccounts": failed_accounts,
            "discoveredArticles": discovered,
            "publishedArticles": len(items),
            "fallbackArticles": fallback_count,
        },
        "items": items,
    }


# ================= 原子发布 =================

def atomic_write_json(path: Path, data: dict) -> None:
    """同目录临时文件 + os.replace 原子替换，避免快照工作流读到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def promote_feed(feed: dict, data_dir: Path, taxonomy_path: Path) -> Path:
    """schema 全量校验通过后原子晋升 current.json，并落一份按日归档副本。"""
    contracts.validate_feed(feed, str(taxonomy_path))
    validate_publishable(feed)
    current = Path(data_dir) / "current.json"
    atomic_write_json(current, feed)
    atomic_write_json(Path(data_dir) / "archive" / f"{feed['targetDate']}.json", feed)
    return current


def validate_publishable(feed: dict) -> None:
    """真实空新闻日可以发布；发现/正文全失败不能清空旧 feed。"""
    stats = feed["stats"]
    if not feed["items"] and (stats["discoveredArticles"] > 0 or stats["failedAccounts"] > 0):
        raise contracts.ContractError("采集或正文加工失败导致空 feed，保留上次成功数据")


def write_state(state_path: Path, target_date: str, promoted: bool, feed: dict | None,
                failure: str | None, task_urls: dict | None = None) -> None:
    prev = {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    state = {
        "lastRunAt": now_bj_iso(),
        "targetDate": target_date,
        "promoted": promoted,
        "failure": failure,
        "taskUrls": task_urls or {},
        "stats": (feed or {}).get("stats"),
        "degraded": (feed or {}).get("degraded"),
        "lastSuccessDate": target_date if promoted else prev.get("lastSuccessDate"),
    }
    atomic_write_json(Path(state_path), state)


# ================= 主流程 =================

def build(target_date: str, work_dir: Path, sources_path: Path, taxonomy_path: Path,
          enrich_fn=None, generated_at: str | None = None,
          min_content_chars: int = 100, cache_path: Path | None = None) -> dict:
    """从运行时 work 目录生成规范化 feed；任何契约违规抛 ContractError。"""
    groups_cfg = load_sources(Path(sources_path))
    raw_dir = Path(work_dir) / target_date / "raw"
    discoveries = load_discoveries(raw_dir, target_date, groups_cfg)
    expected_titles = {a["article_url"]: a["title"]
                       for g in GROUPS for a in discoveries[g]["articles"]
                       if a["extraction_status"] == "complete"}
    if not expected_titles:
        # 三组均完成但当天无文章：合法空 items（ok=true），不是采集失败
        return assemble_feed(target_date, discoveries, [], 0,
                             generated_at or now_bj_iso())
    ok_articles, content_failed = load_content_articles(raw_dir, target_date, expected_titles,
                                                        min_content_chars)
    platform_by_url = {a["article_url"]: a.get("source_platform")
                       for g in GROUPS for a in discoveries[g]["articles"]}
    author_by_url = {a["article_url"]: a.get("author")
                     for g in GROUPS for a in discoveries[g]["articles"]}
    for art in ok_articles:  # 正文 schema 不含平台/作者，从发现结果回填
        art["source_platform"] = platform_by_url.get(art["article_url"])
        art["author"] = author_by_url.get(art["article_url"])

    tx = tag_news.load_taxonomy(str(taxonomy_path))
    enrich_fn = enrich_fn or enrich_news.enrich_items
    enrich_input = [{"title": a["title"], "mpName": a["account_name"],
                     "published_date": a["published_date"], "content_text": a["content_text"]}
                    for a in ok_articles]
    cache_path = Path(cache_path) if cache_path else PROJECT_ROOT / "data" / "manus" / "enrichment_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    enrich_results = enrich_fn(enrich_input, tx, str(cache_path)) if enrich_input else {}

    items, fallback_count, dropped = make_items(ok_articles, enrich_results)
    feed = assemble_feed(target_date, discoveries, items, fallback_count,
                         generated_at or now_bj_iso())
    if content_failed or dropped:
        print(f"正文失败 {len(content_failed)} 篇，加工失败丢弃 {dropped} 篇（不进入发布数据）",
              file=sys.stderr)
    return feed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成并原子发布 Manus 规范化 feed")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--work-dir", default="work/manus")
    parser.add_argument("--data-dir", default="data/manus")
    parser.add_argument("--sources", default="config/manus_sources.json")
    parser.add_argument("--taxonomy", default="config/taxonomy.json")
    parser.add_argument("--generated-at", default=None, help="覆盖生成时间（测试用）")
    parser.add_argument("--no-promote", action="store_true", help="只生成校验，不写 current.json")
    args = parser.parse_args(argv)

    work_dir = PROJECT_ROOT / args.work_dir
    data_dir = PROJECT_ROOT / args.data_dir
    state_path = data_dir / "state.json"
    try:
        feed = build(args.date, work_dir, PROJECT_ROOT / args.sources,
                     PROJECT_ROOT / args.taxonomy, generated_at=args.generated_at,
                     cache_path=data_dir / "enrichment_cache.json")
        validate_publishable(feed)
    except contracts.ContractError as exc:
        # 组失败/schema 不合法：不覆盖上一次 current.json，只记失败状态
        write_state(state_path, args.date, promoted=False, feed=None, failure=str(exc))
        print(f"feed 构建失败，保留上一次 current.json：{exc}", file=sys.stderr)
        return 1
    if args.no_promote:
        contracts.validate_feed(feed, args.taxonomy)
        print(f"feed 校验通过（--no-promote）：{feed['stats']}")
        return 0
    try:
        path = promote_feed(feed, data_dir, PROJECT_ROOT / args.taxonomy)
    except contracts.ContractError as exc:
        write_state(state_path, args.date, promoted=False, feed=None, failure=str(exc))
        print(f"feed 校验失败，未晋升：{exc}", file=sys.stderr)
        return 1
    write_state(state_path, args.date, promoted=True, feed=feed, failure=None)
    print(f"已原子晋升 {path}：发布 {feed['stats']['publishedArticles']} 篇，"
          f"degraded={feed['degraded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
