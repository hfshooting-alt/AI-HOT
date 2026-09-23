"""Explicit single-source detail recovery using immutable saved list responses.

No model calls or publication. Only selected failed/missing-body URLs may use
HTTP; all other requests must replay locally hash-verified original receipts.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from build_manus_feed import atomic_write_json
from manus_source.config import load_sources
from .collector import ROOT, identity, validate_result
from .health import summarize
from .transport import Transport, allowed


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Replay:
    def __init__(self, directory, urls, live):
        self.selected, self.live = set(urls), live
        self.used, self.records = set(), {}
        self.count = self.reused = 0
        for path in sorted(Path(directory).glob('*.json')):
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('redirectHop', 0):
                continue  # Never reconstruct an unverified redirect chain.
            key = (record['url'], record['method'], record.get('requestBodySha256'))
            if key in self.records:
                raise ValueError('Ambiguous repeated request evidence')
            self.records[key] = (record, path)

    def __call__(self, url, *, method='GET', data=None):
        allowed(url)
        if isinstance(data, dict):
            data = urlencode(data).encode()
        elif isinstance(data, str):
            data = data.encode()
        key = (url, method, digest(data) if data else None)
        if key not in self.records:
            raise ValueError('No original request evidence; recovery cannot expand discovery')
        record, path = self.records[key]
        if url in self.selected:
            if method != 'GET' or data or url in self.used:
                raise ValueError('Recovery URL may be requested only once')
            if record.get('httpStatus') in (401, 403, 429):
                raise ValueError('Restricted response requires separate diagnosis')
            self.used.add(url)
            self.count += 1
            return self.live(url, method='GET')
        if record.get('httpStatus') != 200 or record.get('errorType'):
            raise ValueError('Original request failed; not selected for recovery')
        raw = path.with_suffix('.body').read_bytes()
        if digest(raw) != record.get('sha256') or len(raw) > 3_000_000:
            raise ValueError('Saved response integrity mismatch')
        self.reused += 1
        return {'url': url, 'text': raw.decode(record.get('charset', 'utf-8'), errors='replace'),
                'observedAt': record['observedAt'], 'sha256': record['sha256'],
                'receipt': str(path.resolve())}


def recover(collection, account, urls, out, *, fetch_factory=Transport, groups=None):
    from . import platforms, sites
    collection, out = Path(collection).resolve(), Path(out).resolve()
    if out == collection.parent or collection.parent in out.parents:
        raise ValueError('Recovery must use a separate directory outside original evidence')
    if out.exists():
        raise ValueError('Recovery directory already exists; never overwrite an attempt')
    raw = collection.read_bytes()
    data = json.loads(raw)
    if data.get('schemaVersion') != 1 or data.get('collector') != 'direct_site':
        raise ValueError('Unsupported collection')
    groups = groups or load_sources(ROOT / 'config/manus_sources.json')
    expected = {identity(s): s for group in groups.values() for s in group}
    results = data['sources']
    if len(results) != len(expected) or {identity(r['source']) for r in results} != set(expected):
        raise ValueError('Collection does not match current configured sources')
    for result in results:
        validate_result(result, expected[identity(result['source'])], data['collectionWindow'])
    matches = [r for r in results if r['source']['account_name'] == account]
    if len(matches) != 1 or not urls or len(urls) != len(set(urls)) or len(urls) > 20:
        raise ValueError('Select one source and 1..20 unique failed detail URLs')
    original = matches[0]
    failures = [x for x in original.get('diagnostics', []) if x.get('stage') == 'detail']
    failures += original.get('coverage', {}).get('detailFailures', [])
    eligible = {x.get('url') for x in failures}
    eligible.update(i['url'] for i in original['items'] if len(i['content_text'].strip()) < 100)
    eligible.difference_update(i['url'] for i in original['items'] if len(i['content_text'].strip()) >= 100)
    if not set(urls) <= eligible:
        raise ValueError('Only recorded failed or missing-body articles can be recovered')
    for url in urls:
        allowed(url)
    folder = collection.parent / digest(account.encode())[:12]
    # Preflight all selected receipts before any network request.
    replay = Replay(folder / 'http', urls, None)
    for url in urls:
        record = replay.records.get((url, 'GET', None))
        if not record or record[0].get('httpStatus') in (401, 403, 429):
            raise ValueError('Selected URL lacks eligible original HTTP evidence')
    out.mkdir(parents=True)
    atomic_write_json(out / 'recovery-plan.json', {
        'originalCollection': str(collection), 'originalSha256': digest(raw),
        'source': original['source'], 'collectionWindow': data['collectionWindow'],
        'urls': urls, 'maxRequests': len(urls), 'publishes': False})
    replay.live = fetch_factory(out / 'http', max_requests=len(urls))
    adapter = platforms if original['source']['platform'] in ('Tencent News', 'NetEase') else sites
    result = adapter.collect(original['source'], data['collectionWindow'], replay, out)
    validate_result(result, original['source'], data['collectionWindow'])
    # Preserve every prior verified article; recovery can only replace/add targets.
    selected_items = {i['url']: i for i in result['items'] if i['url'] in urls}
    conflicts = []
    for old in original['items']:
        new = selected_items.get(old['url'])
        if new and any(new.get(k) != old.get(k) for k in ('title', 'publishedAt')):
            conflicts.append(old['url'])
            del selected_items[old['url']]
    recovered = sorted(selected_items)
    merged = deepcopy(original)
    merged['items'] = [selected_items.pop(i['url'], i) for i in original['items']]
    merged['items'].extend(selected_items.values())
    # Keep original coverage conservative: replay is not another full source scan.
    if merged['items'] and merged['status'] == 'failed':
        merged['status'] = 'partial'
    merged['diagnostics'] = [x for x in merged.get('diagnostics', [])
                             if not (x.get('stage') == 'detail' and x.get('url') in recovered)]
    if 'detailFailures' in merged.get('coverage', {}):
        merged['coverage']['detailFailures'] = [x for x in merged['coverage']['detailFailures']
                                               if x.get('url') not in recovered]
    for key in ('metadataOnlyItems', 'awaitingBody'):
        if key in merged.get('coverage', {}):
            merged['coverage'][key] = sum(len(i['content_text'].strip()) < 100 for i in merged['items'])
    if 'unresolvedCandidates' in merged.get('coverage', {}):
        merged['coverage']['unresolvedCandidates'] = sum(x.get('stage') == 'detail' for x in merged['diagnostics'])
    merged['recovery'] = {'requested': urls, 'attempted': sorted(replay.used),
        'verified': recovered, 'metadataConflicts': conflicts,
        'newHttpRequests': replay.count, 'replayedResponses': replay.reused,
        'attemptResult': str(out / 'attempt-result.json')}
    merged['health'] = summarize(merged)
    validate_result(merged, original['source'], data['collectionWindow'])
    candidate = deepcopy(data)
    candidate['sources'] = [merged if r['source']['account_name'] == account else r for r in results]
    candidate['recoveryProvenance'] = {'originalCollection': str(collection), 'originalSha256': digest(raw),
                                     'plan': str(out / 'recovery-plan.json')}
    atomic_write_json(out / 'attempt-result.json', result)
    atomic_write_json(out / 'collection.json', candidate)
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--url', action='append', required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    recover(args.collection, args.account, args.url, args.out_dir)


if __name__ == '__main__':
    main()
