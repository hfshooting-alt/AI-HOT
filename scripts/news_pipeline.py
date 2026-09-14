"""Independent source collection and shared, evidence-based news processing.

Raw inputs stay in the candidate workspace. Only processed metadata is published.
"""
import argparse
import copy
import json
from pathlib import Path

import build_snapshot as snapshot
import build_manus_feed as manus
import enrich_news
import screen_news
import tag_news
from manus_source import contracts
from manus_source.config import load_sources
from manus_source.window import ten_am_window, matching_item

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def collect(date, out, api_base='https://aihot.virxact.com'):
    window = ten_am_window(date)
    # Seven-day API pagination avoids losing the start of the fixed window when
    # GitHub schedules start late. The exact 24h filter still applies locally.
    items = snapshot.fetch_items(api_base, snapshot.timestamp(window['start']), '7d')
    payload = {'collectionWindow': window, 'items': [i for i in items if matching_item(window, i)],
               'dailyReport': snapshot.fetch_latest_daily(api_base),
               'hot': snapshot.fetch_hot_topics(api_base)}
    manus.atomic_write_json(Path(out), payload)
    return payload


def load_manus(date, work_dir, groups, enabled=True):
    """Validate groups independently; unavailable groups are explicit failures."""
    window = ten_am_window(date)
    discoveries, audits, metadata = {}, [], {}
    raw_dir = Path(work_dir) / date / 'raw'
    for group, sources in groups.items():
        try:
            if not enabled:
                raise ValueError('not_requested')
            data = read(raw_dir / f'discovery-{group}.json')
            contracts.validate_discovery(data, group, date, [s['account_name'] for s in sources])
            if data.get('collectionWindow') != window:
                raise ValueError('window_mismatch')
        except (OSError, ValueError, KeyError, TypeError):
            data = {'schema_version': 3, 'source_group': group, 'target_date': date,
                    'collectionWindow': window, 'articles': [], 'source_audits': [
                        {'account_name': s['account_name'], 'source_status': 'failed',
                         'article_count': 0, 'note': 'unavailable_or_invalid' if enabled else 'not_requested'}
                        for s in sources]}
        discoveries[group] = data
        for a in data['source_audits']:
            audits.append({'name': a['account_name'], 'collector': 'manus',
                           'status': a['source_status'] if enabled else 'not_requested',
                           'discoveredArticles': a['article_count'], 'usableArticles': 0})
        metadata.update({a['article_url']: a for a in data['articles']
                         if a['extraction_status'] == 'complete'})
    articles = {}
    expected = {url: a['title'] for url, a in metadata.items()}
    dates = {url: a['published_date'] for url, a in metadata.items()}
    for path in sorted(raw_dir.glob('content-batch-*.json')) if enabled else []:
        try:
            ok, _ = contracts.validate_content_batch(read(path), date, expected, 100, dates)
            for a in ok:
                if a['article_url'] in metadata:
                    articles[a['article_url']] = {**a, **metadata[a['article_url']]}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for audit in audits:
        audit['usableArticles'] = sum(a['account_name'] == audit['name'] for a in articles.values())
        if audit['status'] == 'complete' and audit['usableArticles'] < audit['discoveredArticles']:
            audit['status'] = 'partial'
    return discoveries, audits, list(articles.values())


def candidates(aihot, manus_articles):
    """Deduplicate before model calls; prefer available article body over summary."""
    rows = []
    for a in manus_articles:
        source_type, channel, label = manus.source_identity(a)
        rows.append({'id': contracts.stable_article_id(a['account_name'], a['published_date'], a['title']),
                     'title': a['title'], 'url': a['article_url'], 'source': label,
                     'mpName': a['account_name'], 'sourceType': source_type, 'sourceChannel': channel,
                     'sourcePlatform': a.get('source_platform'), 'collector': 'manus',
                     'publishedAt': a['published_at'], 'publishedPrecision': a.get('publishedPrecision', 'datetime'),
                     'timeEvidence': a.get('timeEvidence'),
                     'content_text': a['content_text'], 'evidenceKind': 'article_body'})
    for raw in aihot:
        item = dict(raw)
        item['id'] = str(item.get('id') or item.get('url') or item.get('permalink') or '')
        if not item['id'].startswith('aihot:'):
            item['id'] = 'aihot:' + item['id']
        item['url'] = item.get('url') or item.get('permalink') or ''
        item['collector'] = 'aihot'
        item['mpName'] = (item.get('source', {}).get('name', '')
                          if isinstance(item.get('source'), dict) else item.get('source', ''))
        item['content_text'] = '\n\n'.join(str(item.get(k) or '') for k in ('title', 'summary'))
        item['evidenceKind'] = 'upstream_title_summary'
        rows.append(item)
    unique, urls, titles = [], {}, {}
    for item in rows:
        url = snapshot.norm_url(item['url'])
        title = str(item.get('title') or '').strip().casefold()
        if not title:
            continue
        ref = {'collector': item['collector'], 'source': item.get('mpName') or '',
               'url': item['url'], 'publishedAt': item['publishedAt']}
        previous = urls.get(url) if url else None
        if previous is None:
            previous = titles.get(title)
        if previous is not None:
            if ref not in previous['sourceRefs']:
                previous['sourceRefs'].append(ref)
            continue
        item['sourceRefs'] = [ref]
        if url:
            urls[url] = item
        titles[title] = item
        unique.append(item)
    return sorted(unique, key=lambda i: snapshot.timestamp(i['publishedAt']), reverse=True)


def process(date, workspace, work_dir, enabled=True, *, screen_fn=None, enrich_fn=None):
    workspace = Path(workspace)
    window = ten_am_window(date)
    groups = load_sources(ROOT / 'config/manus_sources.json')
    discoveries, audits, articles = load_manus(date, work_dir, groups, enabled)
    state = read(workspace.parent / 'state.json')
    aihot_status = state['stages'].get('aihot', {}).get('status')
    aihot = {'items': [], 'dailyReport': None, 'hot': {}}
    if aihot_status == 'success':
        aihot = read(workspace / 'inputs/aihot.json')
        if aihot.get('collectionWindow') != window or not isinstance(aihot.get('items'), list):
            raise ValueError('AIHOT input window/schema mismatch')
    audits.insert(0, {'name': 'AIHOT', 'collector': 'aihot',
                     'status': 'complete' if aihot_status == 'success' else 'failed',
                     'discoveredArticles': len(aihot['items']), 'usableArticles': len(aihot['items'])})
    if not any(a['status'] == 'complete' or
               (a['status'] == 'partial' and a['usableArticles'] > 0) for a in audits):
        raise ValueError('All sources unavailable; keep previous publication')
    pool = candidates([i for i in aihot['items'] if matching_item(window, i)], articles)
    tx = copy.deepcopy(tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json')))
    for key in ('relevance', 'enrich'):
        tx.setdefault(key, {}).update(max_new_items_per_run=len(pool), budget_seconds=7200)
    cache_dir = workspace / 'data/cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    screen_fn = screen_fn or screen_news.screen_items
    enrich_fn = enrich_fn or enrich_news.enrich_items
    results, stats = screen_fn(pool, tx, str(cache_dir / 'news_relevance.json'), max_new_items=len(pool))
    manus.atomic_write_json(workspace / 'inputs/relevance-review.json', [
        {'id': i['id'], 'title': i['title'], 'url': i['url'],
         'result': results.get(screen_news.item_key(i), {})} for i in pool])
    quarantined = [{'id': i['id'], 'title': i['title'], 'url': i['url'], 'stage': 'relevance',
                    'reason': '内容或原文证据不足，相关性未核实'} for i in pool
                   if results.get(screen_news.item_key(i), {}).get('status') != 'complete']
    selected = [i for i in pool if results.get(screen_news.item_key(i), {}).get('status') == 'complete'
                and results[screen_news.item_key(i)].get('relevant') is True]
    if pool and len(quarantined) == len(pool):
        raise ValueError('Shared relevance processing unavailable; keep previous publication')
    enriched = enrich_fn(selected, tx, str(cache_dir / 'news_enrichment.json'))
    processed = []
    for item in selected:
        result = enriched.get(enrich_news.enrich_item_key(item), {})
        if (result.get('enrichmentStatus') != 'complete' or not result.get('summary')
                or result.get('classification', {}).get('autoFallback', True)):
            quarantined.append({'id': item['id'], 'title': item['title'], 'url': item['url'],
                                'stage': 'enrichment', 'reason': '摘要或分类未通过校验'})
            continue
        clean = {k: v for k, v in item.items() if k != 'content_text'}
        clean.update(summary=result['summary'], classification=result['classification'],
                     enrichmentStatus='complete', contentSha256=contracts.content_sha256(item['content_text']))
        processed.append(clean)
    if quarantined and not processed:
        raise ValueError('No approved news after summary/classification; keep previous publication')
    collection = {'collectionWindow': window,
                  'degraded': any(a['status'] in ('failed', 'partial') for a in audits),
                  'sources': audits, 'candidateArticles': len(pool), 'publishedArticles': len(processed),
                  'excludedArticles': stats['irrelevant'], 'quarantinedArticles': len(quarantined),
                  'quarantined': quarantined}
    # Fresh, explicitly degraded empty Manus data prevents stale-feed re-injection.
    feed = manus.assemble_feed(date, discoveries,
                              [i for i in processed if i['collector'] == 'manus'], 0, manus.now_bj_iso())
    feed['degraded'] = any(a['status'] in ('failed', 'partial') for a in audits[1:])
    feed['collectionStatus'] = collection
    contracts.validate_feed(feed, str(ROOT / 'config/taxonomy.json'))
    manus.atomic_write_json(workspace / 'data/manus/current.json', feed)
    manus.atomic_write_json(workspace / 'data/manus/archive' / f'{date}.json', feed)
    # Keep extraction grounded in the collected evidence, not our generated summary.
    manus.atomic_write_json(workspace / 'inputs/company-evidence.json', [
        {'id': i['id'], 'url': i['url'], 'content_text': i['content_text']} for i in selected
        if i['id'] in {p['id'] for p in processed}])
    payload = {'collectionWindow': window, 'items': processed, 'collectionStatus': collection,
               'dailyReport': aihot.get('dailyReport'), 'hot': aihot.get('hot') or {}}
    manus.atomic_write_json(workspace / 'inputs/processed.json', payload)
    return payload


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['collect', 'process'])
    p.add_argument('--date', required=True)
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--manus-work-dir', type=Path, default=ROOT / 'work/manus/ten-am')
    p.add_argument('--without-manus', action='store_true')
    args = p.parse_args()
    try:
        if args.command == 'collect':
            collect(args.date, args.workspace / 'inputs/aihot.json')
        else:
            process(args.date, args.workspace, args.manus_work_dir, not args.without_manus)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'News stage failed: {type(exc).__name__}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
