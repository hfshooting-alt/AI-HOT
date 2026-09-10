"""对已筛选 feed 做隔离模型复核；不抓取信源，不写正式数据。"""
import argparse
import copy
import json
import os
import threading
from pathlib import Path

import enrich_news
import tag_news
from llm_common import call_llm
from company_index.inputs import load_articles
from company_index.extraction import extract_articles
from company_index.entities import merge_entities
from company_index.output import assemble, atomic_write, validate
from company_index.config import now_bj_iso


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', required=True)
    parser.add_argument('--work-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--limit', type=int, default=4)
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--max-requests', type=int, default=8)
    args = parser.parse_args()
    feed_path, raw_dir, out = Path(args.feed), Path(args.work_dir), Path(args.output_dir)
    if not args.allow_paid or not 1 <= args.limit <= 18:
        parser.error('需要 --allow-paid；每轮样本上限为 1..18')
    if not 1 <= args.max_requests <= 40:
        parser.error('跨阶段累计请求上限必须为 1..40')
    if not feed_path.is_file() or not list(raw_dir.glob('**/raw/content-batch-*.json')):
        parser.error('feed 或缓存正文目录不存在，拒绝使用错误路径继续调用')
    out = out.resolve()
    if not out.is_relative_to(Path('work').resolve()):
        parser.error('候选输出必须位于 work/ 下')
    source = json.loads(feed_path.read_text(encoding='utf-8'))
    tx = tag_news.load_taxonomy('config/taxonomy.json')
    articles = load_articles(out / 'no-snapshot.json', feed_path, raw_dir, tx)[:args.limit]
    if not articles:
        parser.error('没有可复核文章')
    tx.setdefault('enrich', {}).update(max_attempts=1, max_new_items_per_run=args.limit,
                                      concurrency=2, budget_seconds=900)
    tx.setdefault('companyOverview', {}).update(max_new_articles_per_run=args.limit,
                                               concurrency=2, budget_seconds=900)
    tx['model']['max_output_tokens'] = 1024
    os.environ['LLM_USAGE_LOG'] = str(out / 'usage.jsonl')
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / 'request-budget.json'
    # 兼容已有候选；新请求在发送前占位，超时也计入预算。
    consumed = (json.loads(ledger_path.read_text(encoding='utf-8'))['attempts']
                if ledger_path.exists() else len((out / 'usage.jsonl').read_text(encoding='utf-8').splitlines())
                if (out / 'usage.jsonl').exists() else 0)
    lock = threading.Lock()
    def budgeted_llm(tx, system, user, **kwargs):
        nonlocal consumed
        with lock:
            if consumed >= args.max_requests:
                raise RuntimeError('候选累计调用预算已用尽，未发送请求')
            consumed += 1
            atomic_write(ledger_path, {'attempts': consumed, 'limit': args.max_requests})
        return call_llm(tx, system, user, **kwargs)
    items = [dict(a, mpName=a['sourceName']) for a in articles]
    original_llm = enrich_news.call_llm
    try:
        enrich_news.call_llm = budgeted_llm
        summaries = enrich_news.enrich_items(items, tx, str(out / 'enrichment_cache.json'))
    finally:
        enrich_news.call_llm = original_llm
    # 先完成摘要门禁，再开始下一阶段付费调用。
    if any(r.get('summaryOrigin') != 'model' for r in summaries.values()) or len(summaries) != len(items):
        raise SystemExit('摘要小样本未全部通过，结果已缓存，停止公司抽取和预览更新')
    def bounded_llm(tx, system, user, **kwargs):
        return budgeted_llm(tx, system, user, **kwargs, max_tokens=2048, operation='company_extraction')
    extracts, costs = extract_articles(tx, articles, out / 'extraction_cache.json', bounded_llm)
    if any(r['status'] != 'complete' for r in extracts.values()):
        raise SystemExit('公司抽取未全部成功，结果已缓存，停止预览更新')
    companies = merge_entities(articles, extracts, {}, tx)
    stats = dict(articlesProcessed=len(articles), articlesComplete=len(articles), articlesFailed=0,
                 **costs, companiesTotal=len(companies),
                 productsTotal=sum(len(c['product_names']) for c in companies))
    overview = assemble(companies, stats, now_bj_iso())
    overview['coverageNote'] = f'本轮模型复核覆盖 {len(articles)} 篇已通过 AI 相关性筛选的 Manus 新闻；字段来自原文，未覆盖全部 AIHOT 新闻'
    validate(overview, tx)
    atomic_write(out / 'company-overview.json', overview)
    feed = copy.deepcopy(source)
    by_id = {a['id']: summaries[enrich_news.enrich_item_key(a)] for a in items}
    for item in feed['items']:
        if item['id'] in by_id:
            item.update(by_id[item['id']])
    atomic_write(out / 'feed.json', feed)
    print(json.dumps(stats, ensure_ascii=False))
    for a in articles:
        print(json.dumps({'title': a['title'], 'summary': by_id[a['id']]['summary'],
                          'companies': extracts[a['id']]['companies']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
