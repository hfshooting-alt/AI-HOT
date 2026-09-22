"""Offline, reviewable source migration into a NEW private candidate workspace.

Never publishes, fetches, calls models, or edits the input workspace. Static HTML
and final batch status must be rebuilt by the caller before candidate review.
"""
import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo
from manus_source.source_urls import tencent_article_id

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = ('data/manus', 'data/archive', 'data/cache', 'data/funding',
           'data/company-overview', 'web/public', 'inputs')
SCALARS = ('founded', 'country', 'team', 'business', 'investors', 'total_funding', 'valuation')
FUND_FIELDS = ('product_name', 'industry', *SCALARS)
BUCKETS = ('companies', 'pendingEntities', 'excludedEntities')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(path):
    return {p.relative_to(path).as_posix(): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def url_key(value):
    try:
        p = urlsplit(value or '')
        if p.scheme not in ('http', 'https') or not p.hostname:
            return ''
        # Tencent's observed tracking variants name the same public article.
        tencent_id = tencent_article_id(value)
        if tencent_id:
            return 'https://news.qq.com/rain/a/' + tencent_id
        # Preserve other hosts' query strings: some original article IDs live there.
        return urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))
    except (ValueError, TypeError):
        return ''


def stamp(value):
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (d if d.tzinfo else d.replace(tzinfo=ZoneInfo('Asia/Shanghai'))).timestamp()
    except (ValueError, TypeError, AttributeError):
        return float('-inf')


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def direct_sources(item):
    found = set()
    for value in (item.get('collector'), item.get('sourceType'),
                  (item.get('attribution') or {}).get('source'),
                  (item.get('attribution') or {}).get('name')):
        if isinstance(value, str) and value.lower() in ('aihot', 'manus'):
            found.add(value.lower())
    article_id = str(item.get('articleId') or item.get('id') or '')
    if article_id.startswith(('aihot:', 'manus:')):
        found.add(article_id.split(':')[0])
    for ref in item.get('sourceRefs') or []:
        if isinstance(ref, dict) and ref.get('collector') in ('manus', 'aihot'):
            found.add(ref['collector'])
    for value in (item.get('aihotUrl'), item.get('permalink'),
                  (item.get('links') or {}).get('aihot'), item.get('url')):
        if isinstance(value, str) and urlsplit(value).hostname in ('aihot.news', 'aihot.virxact.com'):
            found.add('aihot')
    return found


class Provenance:
    """Bind article IDs and exact observed URLs; never infer from publisher name."""
    def __init__(self, documents):
        self.ids, self.urls, self.manus_ids, self.articles = {}, {}, {}, {}
        for document in documents:
            for item in walk(document):
                iid = item.get('id')
                if not isinstance(iid, str) or not item.get('title') or not item.get('url'):
                    continue
                kinds = direct_sources(item)
                self.ids.setdefault(iid, set()).update(kinds)
                u = url_key(item.get('url'))
                if u:
                    self.urls.setdefault(u, set()).update(kinds)
                if iid.startswith('manus:'):
                    self.manus_ids.setdefault(u, set()).add(iid)
                    self.articles.setdefault(iid, item)

    def kinds(self, item):
        iid = item.get('articleId') or item.get('id')
        return direct_sources(item) | self.ids.get(iid, set()) | self.urls.get(url_key(item.get('url')), set())

    def article(self, item):
        if 'manus' not in self.kinds(item):
            return None
        out = copy.deepcopy(item)
        key = 'articleId' if 'articleId' in out else 'id'
        iid = out.get(key)
        if not str(iid or '').startswith('manus:'):
            alternatives = self.manus_ids.get(url_key(out.get('url')), set())
            if len(alternatives) != 1:
                raise ValueError('Manus evidence lacks an unambiguous retained article ID; review required')
            out[key] = next(iter(alternatives))
        for field in ('aihotUrl', 'attribution', 'permalink'):
            if field in out and ('aihot' in str(out[field]).lower()):
                out.pop(field)
        if isinstance(out.get('links'), dict):
            out['links'].pop('aihot', None)
        if 'sourceRefs' in out:
            out['sourceRefs'] = [r for r in out['sourceRefs'] if r.get('collector') == 'manus']
        if 'collector' in out:
            out['collector'] = 'manus'
        if out.get('sourceType') == 'aihot':
            out['sourceType'] = 'media'
        return out

    def evidence(self, item):
        if item.get('origin') == 'research':
            # Independent reviewed webpages survive, but relabeling an AIHOT
            # news URL as research must not retain that news contribution.
            kinds = self.urls.get(url_key(item.get('url')), set())
            if kinds == {'aihot'}:
                return None
            if item.get('quote') and item.get('checkedAt') and str(item.get('url', '')).startswith('https://'):
                return copy.deepcopy(item)
            return None
        return self.article(item)


def filter_news(document, provenance):
    """Filter nested snapshot/archive views; metadata is rebuilt separately."""
    if isinstance(document, list):
        out = [filter_news(v, provenance) for v in document]
        out = [v for v in out if v is not None]
        if out and all(isinstance(v, dict) and 'num' in v for v in out):
            for number, item in enumerate(out, 1):
                item['num'] = number
        return out
    if not isinstance(document, dict):
        return document
    if document.get('title') and (document.get('id') or document.get('links')):
        return provenance.article(document)
    if 'aihot' in direct_sources(document) and 'manus' not in direct_sources(document):
        return None
    out = {k: filter_news(v, provenance) for k, v in document.items()
           if not str(k).startswith('aihot:')}
    out = {k: v for k, v in out.items() if v is not None}
    if 'sections' in out:
        out['total'] = sum(len(s.get('items', [])) for s in out['sections'])
        out['lead'] = None  # Original batch narrative may describe removed items.
        if isinstance(out.get('stats'), list):
            counts = {s.get('label'): len(s.get('items', [])) for s in out['sections']}
            out['stats'] = [{**s, 'count': counts.get(s.get('label'), 0)} for s in out['stats']]
    if 'items' in out and isinstance(out['items'], list):
        for key in ('count', 'total'):
            if key in out:
                out[key] = len(out['items'])
    return out


def retained_reference(value, provenance):
    """Remove article-bound review traces while retaining independent review facts."""
    if isinstance(value, list):
        return [v for x in value if (v := retained_reference(x, provenance)) is not None]
    if isinstance(value, dict):
        if value.get('articleId') or str(value.get('id', '')).startswith(('manus:', 'aihot:')):
            return provenance.evidence(value)
        return {k: v for k, x in value.items() if (v := retained_reference(x, provenance)) is not None}
    return value


def clean_entity(record, provenance, audit, checked_at):
    from funding.companies import _country_to_region_label
    row = copy.deepcopy(record)
    old_sources = row.get('sourceArticles', [])
    row['sourceArticles'] = [v for a in old_sources if (v := provenance.article(a)) is not None]
    if not row['sourceArticles']:
        audit.append({'id': row.get('id'), 'name': row.get('company_name'),
                      'action': 'remove_entity_without_manus_news', 'sourceArticleIds': [a.get('id') for a in old_sources]})
        return None
    row['fieldSources'] = {f: [v for e in values if (v := provenance.evidence(e)) is not None]
                           for f, values in row.get('fieldSources', {}).items()}
    if not row['fieldSources'].get('company_name'):
        raise ValueError(f"Retained entity {row.get('id')} has no Manus/research name evidence")
    changes = []
    for field in SCALARS:
        values = sorted(row['fieldSources'].get(field, []),
                        key=lambda e: stamp(e.get('checkedAt') or e.get('publishedAt')), reverse=True)
        current = row.get(field)
        supported = any(e.get('value') == current for e in values)
        selected = current if supported else (values[0].get('value') if current is not None and values else None)
        # Do not resurrect a deliberately reviewed null using historical evidence.
        if selected != current:
            changes.append({'field': field, 'from': current, 'to': selected})
        row[field] = selected
    row['productUpdates'] = [v for u in row.get('productUpdates', []) if (v := provenance.article(u)) is not None]
    permitted = {e.get('value') for e in row['fieldSources'].get('product_names', [])
                 if e.get('origin') == 'article'}
    permitted.update(u.get('name') for u in row['productUpdates'])
    row['fieldSources']['product_names'] = [e for e in row['fieldSources'].get('product_names', []) if e.get('value') in permitted]
    row['product_names'] = [n for n in row.get('product_names', []) if n in permitted]
    names = {e.get('value') for e in row['fieldSources'].get('company_name', [])}
    row['aliases'] = [n for n in row.get('aliases', []) if n in names]
    for field in ('brandProfiles', 'reviewMergedRecords'):
        if field in row:
            row[field] = {n: v for n, p in row[field].items()
                          if (v := clean_entity(p, provenance, audit, checked_at)) is not None}
    for field in ('fieldValueReviews', 'fieldQuarantines'):
        if field in row:
            row[field] = retained_reference(row[field], provenance)
    row['sourceArticles'].sort(key=lambda a: stamp(a.get('publishedAt')), reverse=True)
    latest, earliest = row['sourceArticles'][0].get('publishedAt', ''), row['sourceArticles'][-1].get('publishedAt', '')
    row.update(firstSeenAt=earliest, lastSeenAt=latest, latestReportAt=latest, updatedAt=latest)
    row.setdefault('dims', {})['国家/地区'] = _country_to_region_label(row.get('country'))
    # An old classification scalar has no per-field lineage. Retain it only when
    # the newest report that selected it survives the source filter.
    if old_sources and provenance.article(old_sources[0]) is None:
        row['dims']['行业'] = '其他AI应用'
    if row != record:
        row['profileUpdatedAt'] = checked_at
        audit.append({'id': row['id'], 'name': row['company_name'], 'action': 'retain_manus_supported_entity',
                      'removedArticleIds': [a['id'] for a in old_sources if provenance.article(a) is None],
                      'scalarChanges': changes, 'productsBefore': record.get('product_names', []),
                      'productsAfter': row['product_names']})
    return row


def clean_overview(data, provenance, audit, checked_at, selected):
    out = copy.deepcopy(data)
    for bucket in BUCKETS:
        out[bucket] = [v for r in data.get(bucket, []) if (v := clean_entity(r, provenance, audit, checked_at)) is not None]
    failures = [v for a in data.get('articleFailures', []) if (v := provenance.article(a)) is not None]
    selected_ids = {a['id'] for a in selected}
    failures = [a for a in failures if a['id'] in selected_ids]
    out['articleFailures'] = failures
    out['stats'] = {'articlesProcessed': len(selected_ids), 'articlesComplete': len(selected_ids) - len(failures),
        'articlesFailed': len(failures), 'articlesDeferred': 0, 'modelCalls': 0, 'modelSuccesses': 0,
        'modelFailures': 0, 'cacheHits': 0, 'circuitOpen': False,
        'companiesTotal': len(out['companies']), 'productsTotal': sum(len(r['product_names']) for r in out['companies']),
        'pendingEntities': len(out['pendingEntities']), 'excludedEntities': len(out['excludedEntities'])}
    out['sourceMigration'] = {'mode': 'manus_only', 'checkedAt': checked_at,
        'processingBasis': 'retained_previously_processed_articles; no extraction or cache call', 'newModelCalls': 0}
    for key in ('incrementalProcessing', 'reviewedCorrections', 'qualityReview'):
        out.pop(key, None)
    out['coverageNote'] = '仅保留有 Manus 新闻来源的主体与产品；字段保留 Manus 报道或独立网页核实证据。'
    return out


def funding_supported_values(cache, ids, name):
    from funding.companies import normalize_company_key
    values = {f: set() for f in (*FUND_FIELDS, 'industry_id', 'company_type_id')}
    for key, result in cache.items():
        if not isinstance(result, dict) or result.get('status') != 'complete':
            continue
        if not any(':' + iid + ':' in key for iid in ids):
            continue
        for company in result.get('companies', []):
            if normalize_company_key(company.get('company_name')) == normalize_company_key(name):
                for field in values:
                    if isinstance(company.get(field), str):
                        values[field].add(company[field])
    return values


def clean_funding(data, provenance, cache, audit, selected, checked_at):
    from funding.companies import _country_to_region_label
    out = copy.deepcopy(data)
    companies = []
    for record in data.get('companies', []):
        row = copy.deepcopy(record)
        row['sourceArticles'] = [v for a in row.get('sourceArticles', []) if (v := provenance.article(a)) is not None]
        if not row['sourceArticles']:
            audit.append({'id': row.get('id'), 'name': row.get('company_name'), 'action': 'remove_funding_without_manus_news'})
            continue
        if len(row['sourceArticles']) != len(record.get('sourceArticles', [])):
            supported = funding_supported_values(cache, {a['id'] for a in row['sourceArticles']}, row['company_name'])
            for field in FUND_FIELDS:
                if row.get(field) is not None and row[field] not in supported[field]:
                    audit.append({'id': row['id'], 'action': 'clear_untraceable_mixed_funding_field', 'field': field, 'from': row[field], 'to': None})
                    row[field] = None
            for label, field in [('所属行业', 'industry_id'), ('公司类型', 'company_type_id')]:
                if row.get('dims', {}).get(label) not in supported[field]:
                    row.setdefault('dims', {})[label] = '其他'
            row['dims']['国家/地区'] = _country_to_region_label(row.get('country'))
            row['filledBySearch'] = [f for f in row.get('filledBySearch', []) if row.get(f)]
        companies.append(row)
    out['companies'] = companies
    count = sum((a.get('classification') or {}).get('category', (a.get('classification') or {}).get('cat')) == 'financing' for a in selected)
    out['stats'] = {'articlesProcessed': count, 'modelCalls': 0, 'modelSuccesses': 0, 'modelFailures': 0,
        'cacheHits': 0, 'extractionFailed': 0, 'articlesWithoutFundingInfo': 0,
        'companiesTotal': len(companies), 'companiesSearched': 0}
    out['sourceMigration'] = {'mode': 'manus_only', 'checkedAt': checked_at, 'newModelCalls': 0,
                             'processingBasis': 'retained previous funding records; no extraction'}
    out['coverageNote'] = '仅保留有 Manus 报道支持的融资记录。'
    return out


def sync_status(snapshot, processed, feed):
    library = (snapshot.get('all') or {}).get('items', [])
    selected = (snapshot.get('garenaSelected') or snapshot.get('all') or {}).get('items', [])
    status = copy.deepcopy(snapshot.get('collectionStatus') or processed.get('collectionStatus') or {})
    status['sources'] = [s for s in status.get('sources', []) if s.get('collector') == 'manus']
    selected_ids = {a['id'] for a in selected}
    pending = [a for a in library if (a.get('garenaSelection') or {}).get('status') == 'pending']
    pending_ids = {a['id'] for a in pending}
    old_quarantine = {a['id']: a for a in status.get('quarantined', [])}
    status['quarantined'] = [old_quarantine.get(a['id'], {'id': a['id'], 'title': a.get('title'),
        'url': a.get('url'), 'reason': (a.get('garenaSelection') or {}).get('reason') or 'pending_previous_processing'}) for a in pending]
    status.update(candidateArticles=len(library), articleLibraryCount=len(library), publishedArticles=len(selected_ids),
                  selectedArticles=len(selected_ids), quarantinedArticles=len(pending_ids),
                  excludedArticles=len(library) - len(selected_ids) - len(pending_ids))
    for source in status['sources']:
        belongs = lambda a: a.get('mpName') == source['name'] or any(r.get('collector') == 'manus' and r.get('source') == source['name'] for r in a.get('sourceRefs', []))
        source.update(articleLibraryCount=sum(belongs(a) for a in library), selectedArticles=sum(belongs(a) for a in selected))
        if 'publishedArticles' in source:
            source['publishedArticles'] = source['selectedArticles']
    for target in (snapshot, processed, feed):
        target['collectionStatus'] = copy.deepcopy(status)
    return selected


def clean_public_review(document, overview, checked_at):
    retained = [r for bucket in BUCKETS for r in overview.get(bucket, [])]
    ids = {r['id'] for r in retained}
    names = {n for r in retained for n in [r['company_name'], *r.get('aliases', [])]}
    records = [r for r in document.get('records', []) if r.get('id') in ids
               or (not r.get('id') and (r.get('currentName') or r.get('name')) in names)]
    # These reports describe historical research, not fresh requests or an active
    # full-library review. Keep checkedAt on each original fact/report unchanged.
    return {'checkedAt': document.get('checkedAt'), 'mode': 'manus_only_retained_review_evidence',
        'records': records, 'recordsRetained': len(records),
        'sourceMigration': {'checkedAt': checked_at, 'newModelCalls': 0,
                            'originalReportMetadataInPrivateAudit': True}}


def migrate_workspace(source, output, *, root=ROOT, checked_at=None):
    root, source, output = Path(root).resolve(), Path(source).resolve(), Path(output).resolve()
    work = (root / 'work').resolve()
    if not source.is_relative_to(work) or not output.is_relative_to(work) or source == work or output == work:
        raise ValueError('Both workspaces must be isolated directories under project work/')
    if output.exists() or source == output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Output must be new and disjoint from the input workspace')
    if not source.is_dir() or any(p.is_symlink() or not p.resolve().is_relative_to(source)
                                  for p in [source, *source.rglob('*')]):
        raise ValueError('Input workspace missing or contains symbolic links')
    checked_at = checked_at or datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    before = fingerprint(source)
    news_files = [source / 'web/public/snapshot.json', *sorted((source / 'data/archive').rglob('*.json')),
                  *sorted((source / 'data/manus/archive').glob('*.json')),
                  source / 'data/manus/current.json', source / 'web/public/reviewed-news.json']
    documents = [read(p) for p in news_files if p.exists() and 'cache' not in p.name]
    provenance = Provenance(documents)
    audit = {'schemaVersion': 1, 'checkedAt': checked_at, 'sourceWorkspace': str(source),
        'outputWorkspace': str(output), 'mode': 'manus_only', 'newHttpCalls': 0, 'newModelCalls': 0,
        'readyForPublish': False, 'requiredBeforePublish': ['Rebuild snapshot/history/weekly static outputs and navigation',
            'Overlay actual new batch processed inputs and collection status, then normal candidate validation/review'],
        'originalStats': {}, 'decisions': [], 'files': {}}
    output.mkdir(parents=True)
    for relative in ALLOWED:
        if (source / relative).is_dir():
            shutil.copytree(source / relative, output / relative)
    snapshot = filter_news(read(source / 'web/public/snapshot.json'), provenance)
    processed_path = source / 'inputs/processed.json'
    processed = filter_news(read(processed_path), provenance) if processed_path.exists() else {'items': [], 'allArticles': []}
    feed = filter_news(read(source / 'data/manus/current.json'), provenance)
    selected = sync_status(snapshot, processed, feed)
    for relative, value in [('web/public/snapshot.json', snapshot), ('inputs/processed.json', processed), ('data/manus/current.json', feed)]:
        write(output / relative, value)
    for path in [*(source / 'data/archive').rglob('*.json'), *(source / 'data/manus/archive').glob('*.json')]:
        write(output / path.relative_to(source), filter_news(read(path), provenance))
    for relative in ('inputs/company-evidence.json', 'web/public/reviewed-news.json'):
        if (source / relative).exists():
            write(output / relative, filter_news(read(source / relative), provenance))
    for kind, cleaner in [('company-overview', clean_overview), ('funding', clean_funding)]:
        paths = [source / 'data' / kind / 'current.json', *sorted((source / 'data' / kind / 'archive').glob('*.json'))]
        cache_path = source / 'data/funding/extraction_cache.json'
        cache = read(cache_path) if kind == 'funding' and cache_path.exists() else {}
        for path in paths:
            if not path.exists():
                continue
            original = read(path)
            relative = path.relative_to(source)
            audit['originalStats'][relative.as_posix()] = original.get('stats', {})
            # Historical retained tables do not claim this batch was processed.
            relevant = selected if path.name == 'current.json' else []
            value = cleaner(original, provenance, audit['decisions'], checked_at, relevant) if kind == 'company-overview' else cleaner(original, provenance, cache, audit['decisions'], relevant, checked_at)
            write(output / relative, value)
            if path.name == 'current.json':
                public = 'company-overview.json' if kind == 'company-overview' else 'funding-table.json'
                write(output / 'web/public' / public, value)
    overview = read(output / 'data/company-overview/current.json')
    audit['originalReportMetadata'] = {}
    for filename in ('company-profile-review.json', 'company-research-review.json'):
        path = source / 'web/public' / filename
        if path.exists():
            document = read(path)
            audit['originalReportMetadata'][filename] = {k: v for k, v in document.items() if k != 'records'}
            write(output / 'web/public' / filename, clean_public_review(document, overview, checked_at))
    # Historical research ledger/state stays byte-for-byte inside overview;
    # private cache files and all budget directories are neither rewritten nor used.
    after = fingerprint(output)
    for relative in before.keys() | after.keys():
        if before.get(relative) != after.get(relative):
            audit['files'][relative] = {'beforeSha256': before.get(relative), 'afterSha256': after.get(relative)}
    audit['inputUnchanged'] = before == fingerprint(source)
    if not audit['inputUnchanged']:
        raise ValueError('Input changed during migration; candidate is not reviewable')
    for kind in ('company-overview', 'funding'):
        old, new = read(source / 'data' / kind / 'current.json'), read(output / 'data' / kind / 'current.json')
        audit[kind] = {'before': {b: len(old.get(b, [])) for b in BUCKETS},
                       'after': {b: len(new.get(b, [])) for b in BUCKETS}, 'activeStats': new['stats']}
    audit['news'] = {'beforeLibrary': len((read(source / 'web/public/snapshot.json').get('all') or {}).get('items', [])),
                    'afterLibrary': len((snapshot.get('all') or {}).get('items', [])), 'afterSelected': len(selected)}
    write(output / 'manus-only-migration-audit.json', audit)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-workspace', type=Path, required=True)
    parser.add_argument('--output-workspace', type=Path, required=True)
    args = parser.parse_args()
    def offline(event, unused):
        if event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.posix_spawn'):
            raise RuntimeError('Migration prohibits network and subprocess calls')
    sys.addaudithook(offline)
    report = migrate_workspace(args.source_workspace, args.output_workspace)
    print(json.dumps({k: report[k] for k in ('news', 'company-overview', 'funding', 'inputUnchanged', 'readyForPublish')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
