"""Conservative source-coverage checks from known seed hints, without I/O.

Seeds never establish admission or full-window coverage. The caller must first
validate accepted articles using the ordinary source/time discovery contracts.
"""
from copy import deepcopy
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit

from .source_urls import tencent_article_id


def article_key(url, source):
    """Recognize observed Tencent redirects within one already-bound source."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password:
            return None
        if source.get('platform') == 'Tencent News':
            ident = tencent_article_id(url)
            return 'tencent:' + ident if ident is not None else None
        # No fuzzy title matching or unobserved cross-host aliases. Keep queries
        # for other platforms; their semantics have not been established here.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
    except ValueError:
        return None


def apply_seed_coverage(seed, provided_brief, payload, source, window):
    """Return an independent payload/audit; never promote hints into articles.

    Explicit prose claims of rejection are retained in the original audit note,
    but cannot resolve a URL without an existing machine-verifiable disposition.
    Unmatched hints therefore conservatively prevent a complete declaration.
    """
    result = deepcopy(payload)
    identity = {key: source.get(key) for key in ('account_name', 'platform', 'home_url')}
    report = {'schemaVersion': 1, 'source': identity, 'collectionWindow': deepcopy(window),
              'coverageVerified': False, 'applied': False, 'reason': 'no_bound_seed'}
    if (not isinstance(seed, dict) or seed.get('status') == 'unsupported'
            or seed.get('hintOnly') is not True or seed.get('source') != identity
            or seed.get('collectionWindow') != window):
        return result, report
    candidates = seed.get('candidates', [])
    if not isinstance(candidates, list) or any(not isinstance(row, dict) for row in candidates):
        raise ValueError('Invalid seed candidates for coverage review')
    brief_rows = provided_brief.get('candidates', []) if isinstance(provided_brief, dict) else []
    provided = {article_key(row.get('url'), source) for row in brief_rows if isinstance(row, dict)} - {None}
    accepted = set()
    for article in result['articles']:
        if (article.get('extraction_status') == 'complete'
                and article.get('account_name') == identity['account_name']
                and article.get('source_platform') == identity['platform']
                and article.get('source_home_url') == identity['home_url']):
            key = article_key(article.get('article_url'), source)
            if key is not None:
                accepted.add(key)
    rows, seen = [], set()
    for index, row in enumerate(candidates):
        key = article_key(row.get('url'), source)
        unique = key if key is not None else ('unmatchable', index)
        if unique in seen:
            continue
        seen.add(unique)
        rows.append({'url': row.get('url'), 'title': row.get('title'),
                     'articleKey': key, 'provided': key in provided if key is not None else False,
                     'disposition': 'accepted' if key is not None and key in accepted else 'unresolved'})
    unresolved = [row for row in rows if row['disposition'] == 'unresolved']
    report.update(applied=True, reason='seed_candidates_unresolved' if unresolved else 'no_seed_disposition_gap',
                  candidateHints=len(rows), providedHints=sum(row['provided'] for row in rows),
                  omittedHints=sum(not row['provided'] for row in rows),
                  acceptedHints=len(rows) - len(unresolved), unresolvedHints=len(unresolved),
                  unresolvedProvided=sum(row['provided'] for row in unresolved),
                  unresolvedOmitted=sum(not row['provided'] for row in unresolved), candidates=rows,
                  seedSha256=hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True,
                                                      separators=(',', ':')).encode()).hexdigest())
    audit = next(row for row in result['source_audits'] if row['account_name'] == identity['account_name'])
    report['reportedStatus'] = audit['source_status']
    if unresolved:
        if audit['source_status'] == 'complete':
            audit['source_status'] = 'partial' if audit['article_count'] else 'failed'
        prefix = (f"seed_candidates_unresolved: {len(unresolved)} "
                  f"(provided={report['unresolvedProvided']}, omitted={report['unresolvedOmitted']}); "
                  '候选尚未核验，不代表已确认漏收或可入库文章。')
        audit['note'] = prefix + ' ' + (audit.get('note') or '')
    report['effectiveStatus'] = audit['source_status']
    return result, report
