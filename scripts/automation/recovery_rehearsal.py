"""Synthetic recovery drill in an isolated root, without production publication."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

import tag_news
from . import recovery
from .candidate import read, validate
from .publish import ALLOWED, save
from .runner import tree_digest
from company_index.extraction import cache_key
from funding.extraction import article_cache_key
from funding.inputs import load_articles as funding_articles
from manus_source.window import ten_am_window

ROOT = Path(__file__).resolve().parents[2]
DATE = '2026-09-18'
RUN = 'a' * 32
MODEL = 'recovery-drill-fixture-model'


def setup(root, repository=ROOT):
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(repository / 'config', root / 'config')


def create(root):
    run = root / 'work/runs' / DATE / 'ten-am' / RUN
    w = run / 'workspace'
    for rel in (*ALLOWED, 'inputs'):
        (w / rel).mkdir(parents=True, exist_ok=True)
    window = ten_am_window(DATE)
    items = [dict(id='drill:' + category, title='Recovery Demo Labs ' + category,
        url='https://example.com/drill/' + category, source='Synthetic fixture',
        publishedAt='2026-09-17T12:00:00+08:00', summary='Synthetic fixture: DemoAgent launch and seed funding.',
        classification={'cat': category, 'dims': []}) for category in ('release', 'financing')]
    status = {'collectionWindow': window, 'sources': [{'id': 'fixture', 'status': 'complete'}],
              'candidateArticles': 2, 'publishedArticles': 2, 'excludedArticles': 0,
              'quarantinedArticles': 0, 'quarantined': []}
    save(w / 'inputs/processed.json', dict(collectionWindow=window, collectionStatus=status, items=items))
    save(w / 'web/public/snapshot.json', dict(collectionWindow=window, collectionStatus=status,
        all={'items': items}, daily={'sections': [{'label': 'Fixture', 'items': items}]},
        weekly={'sections': []}, history=[], weeklyNav=[]))
    save(w / 'data/manus/current.json', dict(schemaVersion=2, targetDate=DATE,
        generatedAt=DATE + 'T09:30:00+08:00', collector='manus', ok=True, degraded=False,
        collectionWindow=window, collectionStatus=status, items=[],
        stats={k: 0 for k in ('configuredAccounts', 'completeAccounts', 'failedAccounts',
               'discoveredArticles', 'publishedArticles', 'fallbackArticles')}))
    evidence = [dict(a, content_text='Recovery Demo Labs develops DemoAgent. This is synthetic evidence.') for a in items]
    save(w / 'inputs/company-evidence.json', evidence)
    save(w / 'data/company-overview/current.json', {'companies': []})
    tx = tag_news.load_taxonomy(str(root / 'config/taxonomy.json'))
    company = {'company_name': 'Recovery Demo Labs', 'entity_type': 'company', 'aliases': [],
        'country': '中国', 'business': 'Synthetic recovery test', 'product_names': ['DemoAgent'],
        'products': [{'name': 'DemoAgent', 'relationship': 'owned', 'quote': 'Recovery Demo Labs develops DemoAgent.'}]}
    save(w / 'data/company-overview/extraction_cache.json', {
        cache_key(tx, a): {'status': 'complete', 'companies': [company]} for a in evidence})
    fa = funding_articles(w / 'web/public/snapshot.json', w / 'data/manus/current.json', root / 'work/manus/ten-am', tx)
    save(w / 'data/funding/extraction_cache.json', {
        article_cache_key(tx, a): {'status': 'complete', 'companies': [
            {'company_name': 'Recovery Demo Labs', 'total_funding': 'synthetic 1 million', 'country': '中国'}]} for a in fa})
    save(w / 'web/public/drill.svg', {'synthetic': True})
    save(run / 'state.json', {'date': DATE, 'fingerprint': 'original-failed-fixture-state',
        'modelContext': {'LLM_MODEL': MODEL}, 'published': False,
        'collectionWindow': window, 'recoveryBaseline': {rel: tree_digest(root / rel, portable=True) for rel in ALLOWED},
        'stages': {'news': {'status': 'success'}, 'snapshot': {'status': 'success'},
                   'overview': {'status': 'failed', 'reason': 'simulated post-extraction failure'}}})
    return run


def verify(root, bundle, secret):
    restored = recovery.unpack(root, bundle, secret)
    source = next(restored.glob('work/runs/**/state.json')).parent
    original = (source / 'state.json').read_bytes()
    result = recovery.rebuild(root, source)
    review = Path(result['reviewDirectory'])
    summary = validate(review / 'workspace', root)  # Real gate, no mocked validators.
    overview = read(review / 'workspace/data/company-overview/current.json')
    funding = read(review / 'workspace/data/funding/current.json')
    assert summary['news'] == 2 and summary['companies'] == 1
    assert overview['stats']['cacheHits'] == 2 and overview['stats']['modelCalls'] == 0
    assert overview['companies'][0]['product_names'] == ['DemoAgent']
    assert len(funding['companies']) == 1 and funding['stats']['articlesProcessed'] == 1
    assert (source / 'state.json').read_bytes() == original
    assert not (root / 'web/public/snapshot.json').exists()
    # Delete one cached output: the whole recovery must stop before any request.
    save(source / 'workspace/data/company-overview/extraction_cache.json', {})
    try:
        recovery.rebuild(root, source)
    except ValueError as exc:
        assert '未缓存' in str(exc)
    else:
        raise AssertionError('Missing cache was not blocked')
    # A damaged encrypted archive cannot be restored.
    corrupt = root / 'work/corrupt.bin'
    blob = bytearray(bundle.read_bytes()); blob[-10] ^= 1
    corrupt.write_bytes(blob)
    try:
        recovery.unpack(root, corrupt, secret)
    except ValueError:
        pass
    else:
        raise AssertionError('Damaged ciphertext was accepted')
    return {'status': 'passed', 'synthetic': True, 'paidCalls': 0,
        'news': 2, 'companies': 1, 'products': 1, 'fundingRows': 1,
        'realCandidateValidation': True, 'missingCacheBlocked': True,
        'tamperedBundleBlocked': True, 'originalFailureStatePreserved': True,
        'published': False, 'window': summary['window']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('produce', 'verify'))
    p.add_argument('--bundle', type=Path, required=True)
    args = p.parse_args()
    # The drill cannot reach an API, even if a future implementation adds one.
    def guard(event, values):
        if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise recovery.NeedsModel('Recovery rehearsal forbids networking and subprocesses')
    sys.addaudithook(guard)
    protected = {rel: tree_digest(ROOT / rel, portable=True) for rel in ALLOWED}
    sandbox = ROOT / 'work/recovery-rehearsal' / args.command
    setup(sandbox)
    os.environ['AIHOT_CUTOFF_TIME'] = '09:30'
    os.environ['LLM_MODEL'] = MODEL
    secret = os.environ['PIPELINE_RECOVERY_KEY']
    if args.command == 'produce':
        create(sandbox)
        result = recovery.pack(sandbox, args.bundle, secret)
        result.update(status='encrypted', synthetic=True)
    else:
        result = verify(sandbox, args.bundle, secret)
    assert protected == {rel: tree_digest(ROOT / rel, portable=True) for rel in ALLOWED}
    result['productionDataUnchanged'] = True
    output = ROOT / 'work/recovery-rehearsal' / (args.command + '-report.json')
    save(output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
