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
from company_index.products import replace_article_products
from company_index.identity import apply_reviewed_research
from company_index.output import assemble, promote, validate

ROOT = Path(__file__).resolve().parents[1]


def build(snapshot_path, feed_path, work_dir, previous_path, cache_dir, tx,
          llm_fn=call_llm, generated_at=None, require_complete=False, evidence_path=None, allow_partial=False, replace_product_evidence=False):
    articles = load_articles(snapshot_path, feed_path, work_dir, tx)
    if evidence_path:
        evidence = json.loads(Path(evidence_path).read_text(encoding='utf-8'))
        originals = {r['id']: r for r in evidence}
        if set(originals) != {a['id'] for a in articles}:
            raise ValueError('公司抽取输入与已审核原始证据不一致')
        for article in articles:
            original = originals[article['id']]
            if original['url'] != article['url'] or not original.get('content_text'):
                raise ValueError('公司抽取原始证据缺失或链接不匹配')
            article['content_text'] = original['content_text']
    if require_complete:
        tx = copy.deepcopy(tx)
        tx.setdefault('companyOverview', {}).update(max_new_articles_per_run=len(articles), budget_seconds=7200)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    extracts, cost = extract_articles(tx, articles, cache_dir / "extraction_cache.json", llm_fn)
    previous = load_previous(previous_path)
    previous['companies'] = previous.get('companies', []) + previous.get('pendingEntities', []) + previous.get('excludedEntities', [])
    product_baseline = replace_article_products(previous, {a['id'] for a in articles
        if extracts.get(a['id'], {}).get('status') == 'complete'}) if replace_product_evidence else previous
    companies = apply_reviewed_research(merge_entities(articles, extracts, product_baseline, tx))
    complete = sum(1 for r in extracts.values() if r.get("status") == "complete")
    failed = sum(1 for r in extracts.values() if r.get("status") == "failed")
    stats = {"articlesProcessed": len(articles), "articlesComplete": complete,
             "articlesFailed": failed, "articlesDeferred": cost["articlesDeferred"],
             "modelCalls": cost["modelCalls"], "cacheHits": cost["cacheHits"],
             "companiesTotal": len(companies),
             "productsTotal": sum(len(c["product_names"]) for c in companies)}
    data = assemble(companies, stats, generated_at or now_bj_iso())
    if allow_partial:
        data['articleFailures'] = [{'id': a['id'], 'title': a['title'], 'url': a['url'],
            'reason': '公司资料提取未完成，保留已有公司资料'} for a in articles
            if extracts.get(a['id'], {}).get('status') != 'complete']
    if require_complete and not allow_partial and (complete != len(articles) or failed or cost['articlesDeferred']):
        raise ValueError(f'公司抽取未完整完成：成功{complete}/{len(articles)}，失败{failed}，待处理{cost["articlesDeferred"]}')
    from apply_quality_review import apply
    rules = json.loads((ROOT / 'config/quality_review.json').read_text(encoding='utf-8'))
    data, _, audit = apply(data, {}, rules, tx)
    data['qualityReview'] = audit
    # Report time controls ranking; material profile changes control update time.
    # Legacy updatedAt was a report timestamp, so never migrate it as a verified
    # profile update date. Compare after all identity/review rules have run.
    old_records = {r['id']: r for r in previous.get('companies', [])}
    for bucket in ('companies', 'pendingEntities', 'excludedEntities'):
        for rec in data.get(bucket, []):
            old = old_records.get(rec['id'])
            def material(row):
                return {k: v for k, v in row.items() if k not in (
                    'updatedAt', 'profileUpdatedAt', 'latestReportAt')}
            rec['latestReportAt'] = rec.get('lastSeenAt') or ''
            rec['profileUpdatedAt'] = (old.get('profileUpdatedAt', '')
                if old and material(old) == material(rec) else data['generatedAt'])
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
    parser.add_argument('--replace-product-evidence', action='store_true', help='审核重抽模式：替换成功复核文章的旧产品关联，保留其他文章与失败记录')
    parser.add_argument('--evidence-json', help='本批次审核通过的原始证据，仅保存在隔离工作目录')
    parser.add_argument('--allow-partial', action='store_true', help='隔离单篇公司抽取失败，保留成功更新及旧资料')
    args = parser.parse_args(argv)
    tx = tag_news.load_taxonomy(str(ROOT / args.taxonomy))
    try:
        data = build(ROOT / args.snapshot, ROOT / args.feed, ROOT / args.work_dir,
                     ROOT / args.previous, ROOT / args.cache_dir, tx,
                     generated_at=args.generated_at, require_complete=args.require_complete,
                     evidence_path=args.evidence_json, allow_partial=args.allow_partial, replace_product_evidence=args.replace_product_evidence)
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
