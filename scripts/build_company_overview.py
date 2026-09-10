#!/usr/bin/env python3
"""生成覆盖全部新闻类别的公司与产品 Overview；真实运行需要 LLM，测试可完全离线。"""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tag_news
from llm_common import call_llm
from company_index.config import now_bj_iso
from company_index.inputs import load_articles, load_previous
from company_index.extraction import extract_articles
from company_index.entities import merge_entities
from company_index.identity import apply_reviewed_research
from company_index.output import assemble, promote, validate

ROOT = Path(__file__).resolve().parents[1]


def build(snapshot_path, feed_path, work_dir, previous_path, cache_dir, tx,
          llm_fn=call_llm, generated_at=None, require_complete=False):
    articles = load_articles(snapshot_path, feed_path, work_dir, tx)
    if require_complete:
        tx = copy.deepcopy(tx)
        tx.setdefault('companyOverview', {}).update(max_new_articles_per_run=len(articles), budget_seconds=7200)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    extracts, cost = extract_articles(tx, articles, cache_dir / "extraction_cache.json", llm_fn)
    previous = load_previous(previous_path)
    previous['companies'] = previous.get('companies', []) + previous.get('pendingEntities', []) + previous.get('excludedEntities', [])
    companies = apply_reviewed_research(merge_entities(articles, extracts, previous, tx))
    complete = sum(1 for r in extracts.values() if r.get("status") == "complete")
    failed = sum(1 for r in extracts.values() if r.get("status") == "failed")
    stats = {"articlesProcessed": len(articles), "articlesComplete": complete,
             "articlesFailed": failed, "articlesDeferred": cost["articlesDeferred"],
             "modelCalls": cost["modelCalls"], "cacheHits": cost["cacheHits"],
             "companiesTotal": len(companies),
             "productsTotal": sum(len(c["product_names"]) for c in companies)}
    data = assemble(companies, stats, generated_at or now_bj_iso())
    if require_complete and (complete != len(articles) or failed or cost['articlesDeferred']):
        raise ValueError(f'公司抽取未完整完成：成功{complete}/{len(articles)}，失败{failed}，待处理{cost["articlesDeferred"]}')
    from apply_quality_review import apply
    rules = json.loads((ROOT / 'config/quality_review.json').read_text(encoding='utf-8'))
    data, _, audit = apply(data, {}, rules, tx)
    data['qualityReview'] = audit
    validate(data, tx)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default="web/public/snapshot.json")
    parser.add_argument("--feed", default="data/manus/current.json")
    parser.add_argument("--work-dir", default="work/manus")
    parser.add_argument("--previous", default="data/company-overview/current.json")
    parser.add_argument("--cache-dir", default="data/company-overview")
    parser.add_argument("--data-dir", default="data/company-overview")
    parser.add_argument("--public-dir", default="web/public")
    parser.add_argument("--taxonomy", default="config/taxonomy.json")
    parser.add_argument("--no-promote", action="store_true")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument('--require-complete', action='store_true', help='覆盖全部输入文章；任何失败/待处理均阻止晋升')
    args = parser.parse_args(argv)
    tx = tag_news.load_taxonomy(str(ROOT / args.taxonomy))
    try:
        data = build(ROOT / args.snapshot, ROOT / args.feed, ROOT / args.work_dir,
                     ROOT / args.previous, ROOT / args.cache_dir, tx,
                     generated_at=args.generated_at, require_complete=args.require_complete)
    except ValueError as exc:
        print(f"公司与产品库构建失败，保留上一次产物：{exc}", file=sys.stderr)
        return 1
    if args.no_promote:
        print(f"公司与产品库校验通过（--no-promote）：{data['stats']}")
        return 0
    current, web = promote(data, ROOT / args.data_dir, ROOT / args.public_dir)
    print(f"已原子晋升 {current} 与 {web}：{data['stats']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
