"""已知链接补全；不调用搜索服务，自动建议以暂定值入库。"""
import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from llm_common import resolve_model
from manus_source.crawler import fetch_html, extract_text, truncate_head_tail, _looks_like_risk_page
from .config import SCALAR_FIELDS, now_bj_iso
from .identity import apply_reviewed_research, RULES_PATH
from .research import propose


def read_page(url):
    """仅读取指定公共HTTPS页面；拒绝跨域跳转和非HTML正文。"""
    host = urlsplit(url).hostname or ''
    if urlsplit(url).scheme != 'https' or urlsplit(url).username or not host or host == 'localhost' or re.fullmatch(r'[\d.:]+', host):
        raise ValueError('需要公共网页域名')
    final, html = fetch_html(url, timeout_seconds=15, retries=0)
    if urlsplit(final).hostname != host:
        raise ValueError('页面跨域跳转，保留待核实')
    text, title = extract_text(html)
    if not text or len(text) < 60 or _looks_like_risk_page(html, text):
        raise ValueError('页面正文不足')
    return {'url': url, 'title': title or host, 'text': truncate_head_tail(text, 14000)}


def eligible_fact(fact, row):
    """引文校验之外的业务门禁；待核实也不能混淆融资口径。"""
    fact = copy.deepcopy(fact)
    field, quote, value = fact['field'], fact.get('quote', ''), fact.get('value', '')
    if field in ('total_funding', 'valuation'):
        if re.search(r'拟|计划|意向|尚未|寻求|target|seeking|plans? to|in talks', quote+' '+value, re.I):
            return None
        if not re.search(r'\d', value) or not re.search(r'美元|人民币|欧元|英镑|港元|USD|RMB|CNY|EUR|GBP|HKD|\$', value, re.I):
            return None
        if field == 'total_funding' and not re.search(r'累计|融资总额|total.*rais|raised.*total', quote, re.I):
            return None
    if field == 'team':
        if not any(n and n.casefold() in quote.casefold() for n in [row['company_name'], *row.get('aliases', [])]):
            return None
        if not re.search(r'创始|CEO|首席|团队|总裁|founder|chief|team', quote, re.I):
            return None
        # 人名、履历只保留引文实际支持的部分，不扩写院校和任职。
        fact['value'] = quote[:350]
    return fact


def enrich(data, tx, directory, *, max_requests=5, read_fn=read_page, propose_fn=propose, rules=None):
    if not 1 <= max_requests <= 5:
        raise ValueError('每日已知链接补全最多5次请求')
    result = copy.deepcopy(data)
    rules = rules if rules is not None else json.loads(RULES_PATH.read_text(encoding='utf8'))
    # URL限于已审核且主体名称精确匹配的资料，以及当前记录的新闻链接。
    known = {}
    for rule in rules.get('records', []):
        if rule.get('reviewed') and not rule.get('owner_company'):
            known.setdefault(rule['record_name'], []).extend(f['url'] for f in rule.get('facts', []) if f.get('url', '').startswith('https://'))
    state = result.setdefault('knownLinkResearchState', {})
    report = {'mode': 'known_links', 'checkedAt': now_bj_iso(), 'attempted': 0,
              'filled': 0, 'failed': 0, 'skippedUnchanged': 0, 'deferred': 0, 'records': []}
    pool = [r for r in result['companies'] if any(not r.get(f) for f in SCALAR_FIELDS)]
    # 当天有新闻的主体优先；同日保留原新闻排序。
    pool.sort(key=lambda r: r.get('lastSeenAt', ''), reverse=True)
    pages = {}
    fetched_entities = 0
    for row in pool:
        missing = [f for f in SCALAR_FIELDS if not row.get(f)]
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
                for fact in proposal['facts']:
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
                if facts:
                    row.update(replacement)
                    row['profileUpdatedAt'] = report['checkedAt']
                event.update(status='completed', filledFields=[f['field'] for f in facts],
                             rejectedFacts=proposal.get('rejectedFacts', 0) + semantic_rejected)
                report['filled'] += len(facts)
            except Exception:
                event['status'] = 'model_or_evidence_failed'
                report['failed'] += 1
        state[key]['status'] = event['status']
        report['records'].append(event)
    result['knownLinkResearch'] = report
    return result
