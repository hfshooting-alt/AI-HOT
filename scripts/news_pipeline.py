"""Independent source collection and shared, evidence-based news processing.

Raw inputs stay in the candidate workspace. Only processed metadata is published.
"""
import argparse
import copy
import json
import traceback
from datetime import date as calendar_date, datetime, time
from pathlib import Path

import build_snapshot as snapshot
import build_manus_feed as manus
import enrich_news
import screen_news
import tag_news
from source_status import reason_code
from manus_source import contracts
from manus_source.config import load_sources
from manus_source.checkpoints import publication_time_conflict
from manus_source.window import ten_am_window
from aihot_window import in_window as aihot_in_window

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def collect(date, out, api_base='https://aihot.virxact.com'):
    window = ten_am_window(date)
    # Seven-day API pagination avoids losing the start of the fixed window when
    # GitHub schedules start late. Narrow by AIHOT's timeline, not original date.
    items = snapshot.fetch_items(api_base, snapshot.timestamp(window['start']), '7d')
    payload = {'collectionWindow': window, 'items': [i for i in items if aihot_in_window(window, i)],
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
                           'reasonCode': reason_code(a['source_status'] if enabled else 'not_requested', a.get('note')),
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
                    article = {**a, **metadata[a['article_url']]}
                    if publication_time_conflict(article):
                        article['publicationTimeConflict'] = True
                    articles[a['article_url']] = article
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for audit in audits:
        audit['usableArticles'] = sum(a['account_name'] == audit['name']
                                      and not a.get('publicationTimeConflict') for a in articles.values())
        if audit['status'] == 'complete' and audit['usableArticles'] < audit['discoveredArticles']:
            audit['status'] = 'partial'
            audit['reasonCode'] = ('original_publication_time_conflict' if any(
                a['account_name'] == audit['name'] and a.get('publicationTimeConflict')
                for a in articles.values()) else 'content_incomplete')
    return discoveries, audits, list(articles.values())


def candidate_sort_time(item):
    """Date precision uses a day key for ordering without inventing a publication time."""
    value = item['publishedAt']
    if item.get('publishedPrecision') == 'date':
        return datetime.combine(calendar_date.fromisoformat(value), time.min, tzinfo=snapshot.BJ)
    return snapshot.timestamp(value)


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
    return sorted(unique, key=candidate_sort_time, reverse=True)


def new_model_failure(results, status_field):
    """Cached success cannot certify a stage whose new model calls all failed."""
    attempted = [r for r in results.values() if r.get('modelAttempted') is True and not r.get('cacheHit')]
    succeeded = [r for r in attempted if r.get(status_field) == 'complete'
                 and (status_field != 'enrichmentStatus'
                      or (r.get('classification') or {}).get('autoFallback') is False)]
    failures = [r for r in attempted if (r.get('error') or {}).get('category') != 'content'
                and r not in succeeded]
    if attempted and not succeeded and failures:
        return {'reason': 'no_new_model_success', 'modelCalls': len(attempted), 'modelSuccesses': 0,
                'error': failures[0].get('error') or {'category': 'unknown', 'httpStatus': None, 'systemic': False}}
    return None


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
    conflicts, usable = [], []
    for article in articles:
        if article.get('publicationTimeConflict'):
            conflicts.append({'id': contracts.stable_article_id(article['account_name'], article['published_date'], article['title']),
                'title': article['title'], 'url': article['article_url'], 'stage': 'publication_time',
                'reasonCode': 'original_publication_time_conflict',
                'reason': '列表相对时间与正文原始发布时间冲突，保留证据待核实。'})
        else:
            usable.append(article)
    # Keep the original time evidence private and isolate it before cross-source
    # deduplication, so an independent AIHOT summary can still be processed.
    manus.atomic_write_json(workspace / 'inputs/publication-time-review.json', [
        {k: a.get(k) for k in ('account_name', 'article_url', 'title', 'published_at',
                              'published_date', 'publishedPrecision', 'published_time_text', 'timeEvidence', 'note')}
        for a in articles if a.get('publicationTimeConflict')])
    pool = candidates(aihot['items'], usable)
    from publication_review import review as review_publication
    original_pool_count = len(pool) + len(conflicts)
    pool, time_quarantine = review_publication(pool, window)
    time_quarantine = conflicts + time_quarantine
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
    if stats.get('circuitStopped'):
        manus.atomic_write_json(workspace / 'inputs/model-failure.json', {'stage': 'relevance', 'error': stats['circuitReason']})
        raise ValueError('Shared relevance request circuit stopped; preserve completed caches')
    failure = new_model_failure(results, 'status')
    if failure:
        manus.atomic_write_json(workspace / 'inputs/model-failure.json', {'stage': 'relevance', **failure})
        raise ValueError('Shared relevance has no new model success; preserve completed caches')
    quarantined = [{'id': i['id'], 'title': i['title'], 'url': i['url'], 'stage': 'relevance',
                    'reason': '内容或原文证据不足，相关性未核实'} for i in pool
                   if results.get(screen_news.item_key(i), {}).get('status') != 'complete']
    selected = [i for i in pool if results.get(screen_news.item_key(i), {}).get('status') == 'complete'
                and results[screen_news.item_key(i)].get('relevant') is True]
    if pool and len(quarantined) == len(pool):
        raise ValueError('Shared relevance processing unavailable; keep previous publication')
    enriched = enrich_fn(selected, tx, str(cache_dir / 'news_enrichment.json'))
    manus.atomic_write_json(workspace / 'inputs/enrichment-review.json', [
        {'id': i['id'], 'title': i['title'], 'url': i['url'],
         'result': enriched.get(enrich_news.enrich_item_key(i), {})} for i in selected])
    stopped = next((r for r in enriched.values() if r.get('batchStopped')), None)
    if stopped:
        manus.atomic_write_json(workspace / 'inputs/model-failure.json', {'stage': 'enrichment', 'error': stopped.get('circuitReason')})
        raise ValueError('Shared summary request circuit stopped; preserve completed caches')
    failure = new_model_failure(enriched, 'enrichmentStatus')
    if failure:
        manus.atomic_write_json(workspace / 'inputs/model-failure.json', {'stage': 'enrichment', **failure})
        raise ValueError('Shared summary has no new model success; preserve completed caches')
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
    quarantined.extend(time_quarantine)
    collection = {'collectionWindow': window,
                  'degraded': any(a['status'] in ('failed', 'partial') for a in audits),
                  'sources': audits, 'candidateArticles': original_pool_count, 'publishedArticles': len(processed),
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
        frames = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                  for f in traceback.extract_tb(exc.__traceback__)[-6:]]
        diagnostic = {'command': args.command, 'errorType': type(exc).__name__, 'frames': frames}
        # Preserve execution locations without printing exceptions that may
        # contain upstream bodies, request URLs or credentials.
        manus.atomic_write_json(args.workspace / 'inputs/stage-error.json', diagnostic)
        print(f'News stage failed: {json.dumps(diagnostic, ensure_ascii=False)}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
