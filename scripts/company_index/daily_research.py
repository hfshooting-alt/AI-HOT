"""每日资料补全编排：可选链接发现、网页证据、模型建议及增量入库。"""
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from llm_common import resolve_model
from llm_failures import FailureCircuit, LLMRequestError, safe_error
from .config import SCALAR_FIELDS, now_bj_iso
from .identity import apply_reviewed_research, RULES_PATH
from .research import propose
from .page_evidence import read_page, eligible_fact
from .entities import timestamp
from .research_budget import ResearchBudget, BudgetUnavailable

PROFILE_FIELDS = ('business', 'country', 'founded', 'team')
DAILY_LIMITS = {'entities': 5, 'pages': 10, 'requests': 5}


def input_key(model, row_id, urls, last_seen):
    return hashlib.sha256(json.dumps([1, model, row_id, urls, last_seen],
                                    ensure_ascii=False).encode()).hexdigest()


def research_priority(row, pending_ids):
    if row['id'] in pending_ids:
        return 'pendingOwnership'
    if any(not row.get(field) for field in PROFILE_FIELDS):
        return 'basicProfile'
    return 'financialOnly'


def checked_day(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo('Asia/Shanghai'))).astimezone(
            ZoneInfo('Asia/Shanghai')).date().isoformat()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def daily_usage(state, day):
    usage = dict.fromkeys(DAILY_LIMITS, 0)
    unknown_dates = 0
    legacy = 0
    for entry in state.values():
        entry = entry if isinstance(entry, dict) else {}
        if not all(field in entry for field in ('id', 'name', 'urls', 'missingFields', 'filledFields')):
            legacy += 1
        entry_day = checked_day(entry.get('checkedAt'))
        if entry_day is not None and entry_day != day:
            continue
        if entry_day is None:
            unknown_dates += 1
        # Unattributed/undated legacy attempts reserve capacity, never imply an
        # unsearched company or a successful model response on the current day.
        usage['entities'] += 1
        urls = entry.get('urls')
        usage['pages'] += min(len(urls), 2) if isinstance(urls, list) else 2
        attempted = entry.get('modelAttempted')
        usage['requests'] += int(attempted is not False and entry.get('status') != 'no_readable_page')
    return usage, unknown_dates, legacy


def safe_failure(error):
    # Error class names contain no exception payload, headers or model output.
    result = {'errorType': type(error).__name__}
    if isinstance(error, TimeoutError) or 'Timeout' in type(error).__name__:
        result['failureType'] = 'timeout'
    elif type(error).__name__ == 'HTTPError':
        result['failureType'] = 'http_error'
        code = getattr(error, 'code', None) or getattr(getattr(error, 'response', None), 'status_code', None)
        if type(code) is int and 100 <= code <= 599:
            result['httpStatus'] = code
    elif isinstance(error, ValueError):
        result['failureType'] = {
            '需要公共网页域名': 'invalid_public_url',
            '页面跨域跳转，保留待核实': 'cross_domain_redirect',
            '页面正文不足': 'insufficient_content',
        }.get(str(error), 'invalid_page_or_evidence')
    else:
        result['failureType'] = 'request_or_processing_error'
    return result


def research_error(error, phase):
    if isinstance(error, json.JSONDecodeError):
        return safe_error(LLMRequestError('invalid_response'))
    if isinstance(error, (ValueError, TypeError, KeyError)):
        # propose currently exposes both protocol and local evidence guards as
        # ValueError. Only its known evidence/input guards are non-systemic.
        local_guard = isinstance(error, ValueError) and str(error) in {
            '字段结构无效', '字段缺少逐字来源证据，拒绝写入', '归属公司缺少对应证据',
            '补全需要可回溯的HTTPS网页摘录', '该输入已尝试但未成功，不自动重试付费请求',
            '需要显式允许付费且仍有小样本预算',
        }
        category = 'content' if phase == 'evidence' or local_guard else 'invalid_response'
        return safe_error(LLMRequestError(category))
    return safe_error(error)


def enrich(data, tx, directory, *, max_requests=5, read_fn=read_page, propose_fn=propose, rules=None, discovery_fn=None, budget_dir=None, replay_only=False, full_review=False):
    """Review a finite known-link pool, optionally without the legacy day quota.

    Full review never discovers links or creates Manus tasks. It still reads
    at most two known pages per input and makes at most one new model attempt;
    replay, evidence validation and failure circuits remain unchanged.
    """
    if not full_review and not 1 <= max_requests <= 5:
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
    if discovery_fn and not replay_only and not full_review:
        candidates = [r for r in entities if (r['id'] in pending_ids or any(not r.get(f) for f in PROFILE_FIELDS))
                      and r['id'] not in history]
        if discovered.get('last', {}).get('status') == 'stop_unconfirmed':
            candidates = []
        if candidates:
            selected = sorted(candidates, key=lambda r:timestamp(r.get('lastSeenAt')), reverse=True)[0]
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
              'filled': 0, 'failed': 0, 'skippedUnchanged': 0, 'deferred': 0, 'records': [],
              'pagesFetched': 0, 'dailyLimits': None if full_review else dict(DAILY_LIMITS),
              'fullReview': full_review, 'notAttempted': []}
    day = checked_day(report['checkedAt'])
    model = resolve_model(tx)
    usage, unknown_dates, legacy = daily_usage(state, day)
    report['unknownDateReservations'] = unknown_dates
    pool = [r for r in entities if r['id'] in pending_ids or any(not r.get(f) for f in SCALAR_FIELDS)]
    # 基本资料和待归属主体优先；同组按真实新闻时刻排序。
    pool.sort(key=lambda r: timestamp(r.get('lastSeenAt')), reverse=True)
    pool.sort(key=lambda r: research_priority(r, pending_ids) == 'financialOnly')
    if selected is not None:
        pool.sort(key=lambda r:r['id'] != selected['id'])
    queue = {'total': len(pool), 'basicProfile': 0, 'pendingOwnership': 0, 'financialOnly': 0,
             'processed': 0, 'deferred': 0, 'skippedUnchanged': 0,
             'legacyStateEntries': legacy, 'discoverySelectedId': selected['id'] if selected else None}
    for row in pool:
        queue[research_priority(row, pending_ids)] += 1
    report['queue'] = queue
    if full_review:
        report['batchLimits'] = {'entities': len(pool), 'pages': 2 * len(pool), 'requests': len(pool)}
        report['maxPagesPerEntity'] = 2
        report['discoveryDisabled'] = True
        report['cloudGuard'] = 'same_day_owner_lease'
    budget = ResearchBudget(budget_dir, clock=now_bj_iso,
                            **({'limits': None, 'require_cloud_lease': True}
                               if full_review and not replay_only else {}))
    try:
        journal = budget.snapshot() if replay_only else budget.synchronize(state)
        usage = budget.usage()
    except BudgetUnavailable as error:
        report.update(budgetUnavailable=str(error), dailyLimitReached=False,
                      dailyUsageBefore=None, dailyUsageAfter=None, circuitOpen=False, circuitReason=None)
        report['notAttempted'] = [{'id': r['id'], 'name': r['company_name'], 'reason': 'budget_unavailable'} for r in pool]
        report['deferred'] = queue['deferred'] = len(pool)
        result['knownLinkResearch'] = report
        return result
    report['dailyUsageBefore'] = dict(usage)
    report['cacheHits'] = 0
    report['replayOnly'] = replay_only
    circuit = FailureCircuit()
    # A saved authentication/payment failure remains visible when its input is
    # skipped. Reusing failure state must not silently restart the same service.
    for entry in sorted((item['event'] for item in journal['inputs'].values()
                        if isinstance((e := item.get('event')), dict)
                        and e.get('model') == model and checked_day(e.get('checkedAt')) == day),
                        key=lambda e: timestamp(e.get('checkedAt'))):
        if entry.get('status') in ('completed', 'completed_no_supported_fields'):
            circuit.observe({'status': 'complete'})
        elif isinstance(entry.get('error'), dict):
            circuit.observe({'status': 'failed', 'error': entry['error']})
    pages = {}
    page_failures = {}
    fetched_entities = 0
    for row in pool:
        missing = ['owner_company'] if row['id'] in pending_ids else [f for f in SCALAR_FIELDS if not row.get(f)]
        news_urls = [a['url'] for a in row.get('sourceArticles', []) if a.get('url', '').startswith('https://')]
        urls = list(dict.fromkeys([*known.get(row['company_name'], []), *news_urls]))
        # 搜索常回显作为上下文的新闻；先读取新资料页，避免官网被两页上限挤掉。
        news_keys = {u.rstrip('/') for u in news_urls}
        urls.sort(key=lambda u: u.rstrip('/') in news_keys)
        urls = urls[:2]
        key = input_key(model, row['id'], urls, row.get('lastSeenAt'))
        try:
            saved = budget.lookup(key)
            if saved is None or (replay_only and 'proposal' not in saved):
                # Discovery URLs may exist only in the durable input when the
                # process stopped before publishing companyDiscovery history.
                candidates = [(old_key, old) for old_key, old in journal['inputs'].items()
                    if old['event'].get('id') == row['id']
                    and old['event'].get('name') == row['company_name']
                    and old['event'].get('model') == model
                    and isinstance(old['event'].get('urls'), list)
                    and all(isinstance(u, str) for u in old['event']['urls'])
                    and checked_day(old['event'].get('checkedAt')) is not None]
                for old_key, old in sorted(candidates,
                        key=lambda item: timestamp(item[1]['event']['checkedAt']), reverse=True):
                    event = old['event']
                    previous_urls = {u.rstrip('/') for u in event.get('urls', [])}
                    if not replay_only and any(u.rstrip('/') not in previous_urls | news_keys for u in urls):
                        continue  # A genuinely new profile URL remains a new input.
                    if input_key(model, row['id'], event['urls'], row.get('lastSeenAt')) == old_key:
                        candidate = budget.lookup(old_key)
                        if candidate and 'proposal' in candidate:
                            key, saved = old_key, candidate
                            break
        except BudgetUnavailable as error:
            saved = None
            report['budgetUnavailable'] = str(error)
        replay = saved is not None and 'proposal' in saved
        if saved is not None and not replay:
            state.setdefault(key, copy.deepcopy(saved['event']))
            report['skippedUnchanged'] += 1
            continue
        if replay and key in state:
            report['skippedUnchanged'] += 1
            continue
        event = {'id': row['id'], 'name': row['company_name'], 'urls': urls,
                 'lastSeenAt': row.get('lastSeenAt'),
                 'missingFields': missing, 'filledFields': [], 'checkedAt': report['checkedAt'],
                 'priority': research_priority(row, pending_ids), 'pageResults': [],
                 'model': model, 'modelAttempted': False, 'status': 'attempted'}
        sources = []
        if replay:
            event = copy.deepcopy(saved['event'])
            event.update(modelAttempted=False, cacheHit=True)
            event['checkedAt'] = saved['proposalCheckedAt']
            report['cacheHits'] += 1
        else:
            reason = ('cache_missing' if replay_only else
                      'budget_unavailable' if report.get('budgetUnavailable') else
                      'model_circuit' if circuit.stopped else
                      'run_limit' if not full_review and (report['attempted'] >= max_requests
                                                          or fetched_entities >= max_requests) else None)
            if reason is None:
                try:
                    reason = budget.begin(key, event)
                except BudgetUnavailable as error:
                    report['budgetUnavailable'] = str(error)
                    reason = 'budget_unavailable'
            if reason:
                report['deferred'] += 1
                report['notAttempted'].append({'id': row['id'], 'name': row['company_name'], 'reason': reason})
                continue
            fetched_entities += 1
            state[key] = copy.deepcopy(event)
            for url in urls:
                cached = url in pages or url in page_failures
                if not cached:
                    permission = budget.permission()
                    if permission:
                        report['budgetUnavailable'] = permission
                        event['pageResults'].append({'url': url, 'status': 'skipped', 'reason': permission})
                        break
                    report['pagesFetched'] += 1
                    try:
                        pages[url] = read_fn(url)
                        if not isinstance(pages[url], dict) or not pages[url].get('text'):
                            pages.pop(url, None)
                            raise ValueError('页面正文不足')
                    except Exception as error:
                        page_failures[url] = safe_failure(error)
                if url in page_failures:
                    event['pageResults'].append({'url': url, 'status': 'failed', 'cached': cached,
                                                 **page_failures[url]})
                else:
                    event['pageResults'].append({'url': url, 'status': 'readable', 'cached': cached})
                    sources.append(pages[url])
        if not sources and not replay:
            event['status'] = 'no_readable_page'
            report['failed'] += 1
        else:
            packet = {'record_name': row['company_name'], 'current_record': {f: row.get(f) for f in SCALAR_FIELDS},
                      'missing_fields': missing, 'sources': sources}
            phase = 'proposal'
            try:
                if replay:
                    proposal = saved['proposal']
                else:
                    # run_proposal commits the model slot before calling code.
                    # Its durable event also lets failures report actual attempts.
                    try:
                        proposal, attempted, original_time = budget.run_proposal(
                            key, tx, packet, propose_fn, directory, max_requests=max_requests,
                            **({'full_review': True} if full_review else {}))
                    finally:
                        current = budget.lookup(key)
                        event['modelAttempted'] = current['event'].get('modelAttempted', False)
                        report['attempted'] += int(event['modelAttempted'])
                    event['modelAttempted'] = attempted
                    if not attempted:
                        event['cacheHit'] = True
                        report['cacheHits'] += 1
                    event['checkedAt'] = original_time
                if not isinstance(proposal, dict) or not isinstance(proposal.get('facts'), list):
                    raise LLMRequestError('invalid_response')
                phase = 'evidence'
                facts = []
                semantic_rejected = 0
                candidates_added = 0
                working = copy.deepcopy(row)
                for fact in proposal['facts']:
                    if row['id'] in pending_ids:
                        if fact['field'] == 'owner_company' and fact['value'] != row['company_name']:
                            candidate = {'name':fact['value'],'url':fact['url'],'quote':fact['quote'],
                                'checkedAt':event['checkedAt'],'reason':'网页归属线索经模型提取及逐字核对，法人映射待复核；尚未并入该公司。'}
                            owners = working.setdefault('candidateOwners', [])
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
                        'checkedAt': event['checkedAt'],
                        'reason': 'DeepSeek根据已知网页提出，原文引文已校验；主体及字段口径仍待复核。'})
                replacement = apply_reviewed_research([working], {'checkedAt': event['checkedAt'],
                    'records': [{'record_name': row['company_name'], 'reviewed': True, 'facts': facts}]})[0]
                filled_fields = list(dict.fromkeys(f['field'] for f in facts
                    if replacement.get(f['field']) != row.get(f['field'])))
                if filled_fields or candidates_added:
                    row.update(replacement)
                    row['profileUpdatedAt'] = max((row.get('profileUpdatedAt'), event['checkedAt']), key=timestamp)
                event.update(status='completed' if filled_fields or candidates_added else 'completed_no_supported_fields',
                             filledFields=filled_fields + (['candidateOwners'] if candidates_added else []),
                             rejectedFacts=proposal.get('rejectedFacts', 0) + semantic_rejected)
                report['filled'] += len(filled_fields) + candidates_added
                circuit.observe({'status': 'complete'})
            except BudgetUnavailable as error:
                report['budgetUnavailable'] = str(error)
                event.update(status='budget_deferred', budgetReason=str(error))
                report['deferred'] += 1
                report['notAttempted'].append({'id': row['id'], 'name': row['company_name'], 'reason': str(error)})
            except Exception as error:
                event['status'] = 'model_or_evidence_failed'
                event.update(safe_failure(error))
                event['error'] = research_error(error, phase)
                circuit.observe({'status': 'failed', 'error': event['error']})
                report['failed'] += 1
        state[key] = copy.deepcopy(event)
        # Replaying a result must not erase the original charged attempt.
        if not replay:
            try:
                budget.finish(key, event)
            except BudgetUnavailable as error:
                report['budgetUnavailable'] = str(error)
        report['records'].append(event)
    queue.update(processed=len(report['records']), deferred=report['deferred'],
                 skippedUnchanged=report['skippedUnchanged'])
    try:
        usage = budget.usage()
    except BudgetUnavailable as error:
        report['budgetUnavailable'] = str(error)
    report['dailyUsageAfter'] = usage
    report['dailyLimitReached'] = not full_review and any(usage[k] >= limit for k, limit in DAILY_LIMITS.items())
    report.update(circuitOpen=circuit.stopped, circuitReason=circuit.reason)
    result['knownLinkResearch'] = report
    return result
