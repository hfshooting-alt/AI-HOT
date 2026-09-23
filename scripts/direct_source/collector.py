"""Collect one frozen window from all configured sources, isolating failures."""
import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from build_manus_feed import atomic_write_json
from manus_source.config import load_sources
from manus_source.window import matching_item, ten_am_window
from .transport import Transport, allowed
from .health import summarize

ROOT = Path(__file__).resolve().parents[2]


def identity(source):
    return tuple(source.get(k) for k in ('account_name', 'platform', 'home_url'))


def validate_result(result, source, window):
    if not isinstance(result, dict) or identity(result.get('source', {})) != identity(source):
        raise ValueError('Source identity mismatch')
    if result.get('status') not in ('complete', 'partial', 'failed') or not isinstance(result.get('items'), list):
        raise ValueError('Invalid source disposition')
    if result['status'] == 'failed' and result['items']:
        raise ValueError('Failed source cannot publish unverified items')
    seen = set()
    for item in result['items']:
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ('title', 'url', 'publishedAt')):
            raise ValueError('Missing article metadata')
        proof = item.get('validation')
        if (not isinstance(proof, dict) or any(proof.get(k) is not True for k in
                ('titleMatched', 'sourceMatched', 'publicationTimeVerified')) or not matching_item(window, item)):
            raise ValueError('Unverified publication window')
        allowed(item['url'])
        if item['url'] in seen:
            raise ValueError('Duplicate source URL')
        seen.add(item['url'])
        if not isinstance(item.get('content_text'), str):
            raise ValueError('Invalid body')
    return result


def collect(window, directory, *, groups=None, fetch_factory=Transport):
    from . import platforms, sites
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / 'collection.json'
    if output.exists():
        raise ValueError('Collection already exists; reuse it or choose a new run directory')
    groups = groups or load_sources(ROOT / 'config/manus_sources.json')
    entries = [(g, s) for g, sources in groups.items() for s in sources]
    atomic_write_json(directory / 'plan.json', {'collectionWindow': window,
        'sources': [s for _, s in entries], 'maxConcurrency': 3, 'collector': 'direct_site',
        'maxRequestsPerSource': 240, 'maxPagesPerSource': 10, 'maxDetailsPerSource': 200})

    def one(entry):
        group, source = entry
        folder = directory / hashlib.sha256(source['account_name'].encode()).hexdigest()[:12]
        fetch = fetch_factory(folder / 'http')
        try:
            adapter = platforms if source['platform'] in ('Tencent News', 'NetEase') else sites
            result = validate_result(adapter.collect(source, window, fetch, folder), source, window)
        except Exception as exc:
            result = {'source': source, 'items': [], 'status': 'failed', 'listRows': 0,
                      'reason': 'adapter_failed', 'errorType': type(exc).__name__, 'coverage': {}}
            # Private location trace is useful without leaking server responses.
            import traceback
            result['traceback'] = traceback.format_exc()
        result.update(group=group, httpRequests=fetch.count)
        result['health'] = summarize(result)
        atomic_write_json(folder / 'result.json', result)
        print(f"[{source['account_name']}] {result['status']} / {len(result['items'])} verified", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(one, entries))
    payload = {'schemaVersion': 1, 'collector': 'direct_site', 'collectionWindow': window,
               'maxConcurrency': 3, 'sources': results}
    atomic_write_json(output, payload)
    return payload


def load(path, date, groups):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    window = ten_am_window(date)
    if data.get('schemaVersion') != 1 or data.get('collector') != 'direct_site' or data.get('collectionWindow') != window:
        raise ValueError('Direct collection contract/window mismatch')
    expected = {identity(s): (group, s) for group, sources in groups.items() for s in sources}
    results = data.get('sources', [])
    if len(results) != len(expected) or {identity(r.get('source', {})) for r in results} != set(expected):
        raise ValueError('Direct collection must disclose every configured source exactly once')
    discoveries = {g: {'collectionWindow': window, 'source_audits': [], 'articles': []} for g in groups}
    audits, articles = [], []
    for result in results:
        group, source = expected[identity(result['source'])]
        validate_result(result, source, window)
        from .reviews import apply as apply_reviews
        result = {**result, 'items': apply_reviews(source, result['items'])}
        complete = result['status'] == 'complete'
        audit = {'name': source['account_name'], 'collector': 'direct_site', 'status': result['status'],
                 'reasonCode': 'complete' if complete else ('source_unavailable' if result['status'] == 'failed' else 'boundary_unverified'),
                 'discoveredArticles': len(result['items']),
                 'articleLibraryCount': len(result['items']),
                 'usableArticles': sum(len(i['content_text'].strip()) >= 100 for i in result['items']),
                 'coverage': result.get('coverage', {}),
                 'health': summarize(result)}
        audits.append(audit)
        discoveries[group]['source_audits'].append({'account_name': source['account_name'],
            'source_status': result['status'], 'article_count': len(result['items'])})
        for item in result['items']:
            body = item['content_text'].strip()
            article = {'account_name': source['account_name'], 'source_platform': source['platform'],
                'title': item['title'], 'article_url': item['url'],
                'published_at': item['publishedAt'], 'published_date': item['publishedAt'][:10],
                'publishedPrecision': item.get('publishedPrecision', 'datetime'),
                'timeEvidence': item.get('timeEvidence'), 'collector': 'direct_site',
                'content_text': body if len(body) >= 100 else '', 'metadataOnly': len(body) < 100,
                'extraction_status': 'complete'}
            articles.append(article)
            discoveries[group]['articles'].append(article)
    return discoveries, audits, articles


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date', required=True)
    p.add_argument('--out-dir', type=Path, required=True)
    args = p.parse_args()
    collect(ten_am_window(args.date), args.out_dir)


if __name__ == '__main__':
    main()
