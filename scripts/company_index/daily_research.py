"""每日资料补全编排：可选链接发现、网页证据、模型建议及增量入库。"""
import copy
import hashlib
import json
from pathlib import Path

from llm_common import resolve_model
from .config import SCALAR_FIELDS, now_bj_iso
from .identity import apply_reviewed_research, RULES_PATH
from .research import propose
from .page_evidence import read_page, eligible_fact


def enrich(data, tx, directory, *, max_requests=5, read_fn=read_page, propose_fn=propose, rules=None, discovery_fn=None):
    if not 1 <= max_requests <= 5:
        raise ValueError('每日已知链接补全最多5次请求')
    result = copy.deepcopy(data)
    rules = rules if rules is not None else json.loads(RULES_PATH.read_text(encoding='utf8'))
    # URL限于已审核且主体名称精确匹配的资料，以及当前记录的新闻链接。
    known = {}
    for rule in rules.get('records', []):
        if rule.get('reviewed') and not rule.get('owner_company'):
            known.setdefault(rule['record_name'], []).extend(f['url'] for f in rule.get('facts', []) if f.get('url', '').startswith('https://'))
    discovered = result.setdefault('companyDiscovery', {'history': {}})
    history = discovered.setdefault('history', {})
    pending_ids = {r['id'] for r in result.get('pendingEntities', [])}
    entities = [*result['companies'], *result.get('pendingEntities', [])]
    for rec in entities:
        old = history.get(rec['id'], {})
        known[rec['company_name']] = [*old.get('urls', []), *known.get(rec['company_name'], [])]
    selected = None
    if discovery_fn:
        candidates = [r for r in entities if (r['id'] in pending_ids or not r.get('country') or not r.get('founded'))
                      and r['id'] not in history]
        if discovered.get('last', {}).get('status') == 'stop_unconfirmed':
            candidates = []
        if candidates:
            selected = sorted(candidates, key=lambda r:r.get('lastSeenAt',''), reverse=True)[0]
            try:
                found = discovery_fn(selected)
            except Exception as error:
                found = {'name':selected['company_name'], 'status':'discovery_unavailable',
                         'urls':[], 'errorType':type(error).__name__}
            discovered['last'] = found
            if found['status'] not in ('quota_used','quota_unavailable','missing_key','discovery_unavailable'):
                history[selected['id']] = found
            known[selected['company_name']] = [*found.get('urls', []), *known.get(selected['company_name'], [])]
    state = result.setdefault('knownLinkResearchState', {})
    report = {'mode': 'known_links', 'checkedAt': now_bj_iso(), 'attempted': 0,
              'filled': 0, 'failed': 0, 'skippedUnchanged': 0, 'deferred': 0, 'records': []}
    pool = [r for r in entities if any(not r.get(f) for f in SCALAR_FIELDS)]
    # 当天有新闻的主体优先；同日保留原新闻排序。
    pool.sort(key=lambda r: r.get('lastSeenAt', ''), reverse=True)
    if selected is not None:
        pool.sort(key=lambda r:r['id'] != selected['id'])
    pages = {}
    fetched_entities = 0
    for row in pool:
        missing = ['owner_company'] if row['id'] in pending_ids else [f for f in SCALAR_FIELDS if not row.get(f)]
        urls = list(dict.fromkeys([*known.get(row['company_name'], []),
            *(a['url'] for a in row.get('sourceArticles', []) if a.get('url', '').startswith('https://'))]))[:2]
        key = hashlib.sha256(json.dumps([1, resolve_model(tx), row['id'], urls,
            row.get('lastSeenAt')], ensure_ascii=False).encode()).hexdigest()
        if key in state:
            report['skippedUnchanged'] += 1
            continue
        if report['attempted'] >= max_requests or fetched_entities >= max_requests:
            report['deferred'] += 1
            continue
        fetched_entities += 1
        sources = []
        for url in urls:
            try:
                if url not in pages:
                    pages[url] = read_fn(url)
                sources.append(pages[url])
            except Exception:
                pass  # 一页失败不影响同主体另一页或其他主体。
        event = {'id': row['id'], 'name': row['company_name'], 'urls': urls, 'filledFields': []}
        state[key] = {'checkedAt': report['checkedAt'], 'status': 'attempted'}
        if not sources:
            event['status'] = 'no_readable_page'
            report['failed'] += 1
        else:
            packet = {'record_name': row['company_name'], 'current_record': {f: row.get(f) for f in SCALAR_FIELDS},
                      'missing_fields': missing, 'sources': sources}
            report['attempted'] += 1
            try:
                proposal = propose_fn(tx, packet, Path(directory), allow_paid=True,
                                      max_requests=max_requests, isolate_invalid=True)
                facts = []
                semantic_rejected = 0
                candidates_added = 0
                for fact in proposal['facts']:
                    if row['id'] in pending_ids:
                        if fact['field'] == 'owner_company' and fact['value'] != row['company_name']:
                            candidate = {'name':fact['value'],'url':fact['url'],'quote':fact['quote'],
                                'checkedAt':report['checkedAt'],'reason':'网页归属线索经模型提取及逐字核对，法人映射待复核；尚未并入该公司。'}
                            owners = row.setdefault('candidateOwners', [])
                            if not any(c['name']==candidate['name'] and c['url']==candidate['url'] for c in owners):
                                owners.append(candidate)
                                candidates_added += 1
                        continue
                    if proposal.get('owner_company') and proposal['owner_company'] != row['company_name']:
                        continue  # 模型提出不同所属主体时，不能把其资料灌入当前公司。
                    if fact['field'] not in missing:
                        continue
                    fact = eligible_fact(fact, row)
                    if fact is None:
                        semantic_rejected += 1
                        continue
                    # 不把逐字引文通过冒充完整人工核验；自动补全不改归属或既有值。
                    facts.append({**fact, 'verificationStatus': 'provisional',
                        'checkedAt': report['checkedAt'],
                        'reason': 'DeepSeek根据已知网页提出，原文引文已校验；主体及字段口径仍待复核。'})
                replacement = apply_reviewed_research([row], {'checkedAt': report['checkedAt'],
                    'records': [{'record_name': row['company_name'], 'reviewed': True, 'facts': facts}]})[0]
                if facts or candidates_added:
                    row.update(replacement)
                    row['profileUpdatedAt'] = report['checkedAt']
                event.update(status='completed', filledFields=[f['field'] for f in facts] + (['candidateOwners'] if candidates_added else []),
                             rejectedFacts=proposal.get('rejectedFacts', 0) + semantic_rejected)
                report['filled'] += len(facts) + candidates_added
            except Exception:
                event['status'] = 'model_or_evidence_failed'
                report['failed'] += 1
        state[key]['status'] = event['status']
        report['records'].append(event)
    result['knownLinkResearch'] = report
    return result
