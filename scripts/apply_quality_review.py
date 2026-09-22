"""Replay reviewed decisions against a candidate directory, without API calls.

Original model artifacts remain untouched; outputs and audit are written separately.
"""
import argparse
import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import tag_news
from company_index.products import refresh
from company_index.entities import timestamp
from company_index.identity import apply_reviewed_research
from company_index.output import atomic_write, validate
from company_index.config import SCALAR_FIELDS


def fingerprint(item):
    return hashlib.sha256(json.dumps([item.get('title'), item.get('summary')], ensure_ascii=False).encode()).hexdigest()


def _field_decisions(rules):
    allowed = {'valuation', 'total_funding', 'investors', 'country', 'founded', 'team', 'business'}
    return [d for d in rules.get('fieldValueReviews', []) if d.get('field') in allowed
            and all(isinstance(d.get(k), str) and d[k].strip()
                    for k in ('company', 'from', 'articleId', 'quote', 'reason'))
            and 'to' in d and (d['to'] is None or isinstance(d['to'], str) and d['to'].strip())
            and d['from'] != d['to']]


def _record_value_review(row, decision):
    reviews = row.setdefault('fieldValueReviews', [])
    if decision not in reviews:
        reviews.append(copy.deepcopy(decision))


def _article_extraction_review(article, decisions):
    """Select one exact evidence binding; never infer a match from absent fields."""
    if not isinstance(decisions, list):
        raise ValueError('articleExtractionReviews 必须为数组')
    if not all(isinstance(article.get(k), str) and article[k]
               for k in ('id', 'title', 'url', 'content_text')):
        return None
    body_hash = hashlib.sha256(article['content_text'].encode('utf-8')).hexdigest()
    matches = [d for d in decisions if isinstance(d, dict)
        and (d.get('articleId'), d.get('title'), d.get('url'), d.get('contentSha256'))
        == (article['id'], article['title'], article['url'], body_hash)]
    if len(matches) > 1:
        raise ValueError('同一文章证据存在多条完整抽取审校，禁止按顺序覆盖')
    if not matches:
        return None
    decision = matches[0]
    required = {'articleId', 'title', 'url', 'contentSha256', 'reviewedAt', 'reason', 'companies'}
    if (set(decision) != required
            or any(not isinstance(decision.get(k), str) or not decision[k].strip()
                   for k in required - {'companies'})
            or not re.fullmatch(r'[0-9a-f]{64}', decision['contentSha256'])
            or not isinstance(decision['companies'], list)):
        raise ValueError('完整抽取审校的证据或结构不合法')
    try:
        datetime.fromisoformat(decision['reviewedAt'].replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('完整抽取审校的审核日期不合法') from None
    return decision


def _reviewed_companies(article, companies):
    # Import only while replaying a matched review, after extraction modules
    # have initialized. Read taxonomy directly: this validator needs no keys.
    from company_index.extraction import normalize_company
    from company_index.products import normalize as normalize_products
    from funding.companies import normalize_company_key
    tx = json.loads((Path(__file__).resolve().parents[1] / 'config/taxonomy.json').read_text(encoding='utf-8'))
    expected = {'company_name', 'entity_type', 'aliases', 'product_names', 'products', 'industry_id', *SCALAR_FIELDS}
    seen = set()
    for company in companies:
        if (not isinstance(company, dict) or set(company) != expected
                or not isinstance(company.get('company_name'), str) or not company['company_name'].strip()
                or company.get('entity_type') not in ('company', 'product')
                or not isinstance(company.get('industry_id'), str)
                or any(company.get(k) is not None and not isinstance(company[k], str) for k in SCALAR_FIELDS)
                or any(not isinstance(company.get(k), list)
                       or any(not isinstance(v, str) or not v.strip() for v in company[k])
                       for k in ('aliases', 'product_names'))
                or not isinstance(company.get('products'), list)):
            raise ValueError('完整抽取审校的公司结构不合法')
        for product in company['products']:
            if (not isinstance(product, dict) or set(product) != {'name', 'relationship', 'quote'}
                    or not isinstance(product.get('name'), str) or not product['name'].strip()
                    or product.get('relationship') not in ('owned', 'integrated', 'used', 'unknown')
                    or not isinstance(product.get('quote'), str)):
                raise ValueError('完整抽取审校的产品关系结构不合法')
        # Normalization must be lossless: never turn a malformed reviewed row
        # into a broader fallback, or silently discard a bad product/quote.
        if (normalize_company(company, tx) != company
                or normalize_products(company['products'], article) != company['products']):
            raise ValueError('完整抽取审校必须已规范化，产品引文必须匹配原文')
        key = normalize_company_key(company['company_name'])
        if not key or key in seen:
            raise ValueError('完整抽取审校包含重复或无效主体')
        seen.add(key)
    return copy.deepcopy(companies)


def apply_article_value_reviews(articles, extracts, rules, *, extraction_reviews=True):
    """Correct only a reviewed article's extraction before normal temporal merging.

    Return a deep copy so successful model caches retain their original values
    and cache keys. The saved quote must still occur in the collected evidence.
    """
    corrected = copy.deepcopy(extracts)
    decisions = _field_decisions(rules)
    for article in articles:
        extracted = corrected.get(article['id']) or {}
        if extracted.get('status') != 'complete':
            continue
        if extraction_reviews:
            decision = _article_extraction_review(article, rules.get('articleExtractionReviews', []))
            if decision is not None:
                extracted['companies'] = _reviewed_companies(article, decision['companies'])
                extracted['articleExtractionReview'] = {
                    k: copy.deepcopy(v) for k, v in decision.items() if k != 'companies'}
        content = re.sub(r'\s+', '', article.get('content_text') or '')
        for decision in decisions:
            if (article['id'] != decision['articleId']
                    or re.sub(r'\s+', '', decision['quote']) not in content):
                continue
            for company in extracted.get('companies', []):
                field = decision['field']
                if company.get('company_name') == decision['company'] and company.get(field) == decision['from']:
                    company[field] = decision['to']
                    _record_value_review(company, decision)
    return corrected


def apply_field_value_reviews(rows, rules, *, allow_updates=True):
    """Legacy merged rows may change only when the winning field source is known.

    General sourceArticles never establishes which article supplied a field.
    Ambiguous dates or tied sources from different articles leave the row alone.
    """
    for row in rows:
        for decision in _field_decisions(rules):
            field = decision['field']
            if (row.get('company_name') != decision['company']
                    or row.get(field) not in (decision['from'], decision['to'])):
                continue
            if not allow_updates and row[field] != decision['to']:
                continue
            evidence = row.get('fieldSources', {}).get(field) or []
            if not evidence:
                continue
            if len(evidence) > 1:
                dates = [timestamp(e.get('publishedAt')) for e in evidence]
                if float('-inf') in dates:
                    continue
                evidence = [e for e, date in zip(evidence, dates) if date == max(dates)]
            if (any(e.get('articleId') != decision['articleId'] or e.get('origin', 'article') != 'article'
                    for e in evidence)
                    or not any(e.get('value') == row[field] for e in evidence)):
                continue
            row[field] = decision['to']
            _record_value_review(row, decision)
            for source in row.get('fieldSources', {}).get(field, []):
                if decision['to'] is not None and source.get('articleId') == decision['articleId'] and source.get('value') in (decision['from'], decision['to']):
                    source.update(value=decision['to'], originalValue=decision['from'],
                                  quote=decision['quote'], reviewedAt=decision.get('reviewedAt'))


def apply(overview, snapshot, rules, tx, *, review_field_values=True):
    overview, snapshot = copy.deepcopy(overview), copy.deepcopy(snapshot)
    rows = overview['companies'] = apply_reviewed_research(overview['companies'])
    apply_field_value_reviews(rows, rules, allow_updates=review_field_values)
    audit = {'merged': [], 'pending': [], 'excluded': [], 'classifications': [], 'staleDecisions': []}
    for source, owner in rules['aliases'].items():
        src = next((r for r in rows if r['company_name'] == source), None)
        dst = next((r for r in rows if r['company_name'] == owner), None)
        if not src or not dst:
            continue
        dst.setdefault('reviewMergedRecords', {})[source] = copy.deepcopy(src)
        dst['aliases'] = list(dict.fromkeys(dst['aliases'] + [source] + src['aliases']))
        dst.setdefault('productUpdates', []).extend(u for u in src.get('productUpdates', []) if u not in dst.get('productUpdates', []))
        dst['product_names'] = list(dict.fromkeys(dst['product_names'] + src['product_names']))
        existing = {a['id'] for a in dst['sourceArticles']}
        dst['sourceArticles'].extend(a for a in src['sourceArticles'] if a['id'] not in existing)
        # Conflicting scalar facts stay in the preserved original record for review.
        for field, evidence in src['fieldSources'].items():
            if field not in ('company_name', 'product_names'):
                if not dst.get(field):
                    dst[field] = src.get(field)
                evidence = [e for e in evidence if e['value'] == dst.get(field)]
            bucket = dst['fieldSources'].setdefault(field, [])
            for e in evidence:
                if e not in bucket:
                    bucket.append(e)
        dst['lastSeenAt'] = max(dst['lastSeenAt'], src['lastSeenAt'], key=timestamp)
        dst['firstSeenAt'] = min(dst['firstSeenAt'], src['firstSeenAt'], key=timestamp)
        rows.remove(src)
        audit['merged'].append({'from': source, 'to': owner})
    pending = overview.setdefault('pendingEntities', [])
    excluded = overview.setdefault('excludedEntities', [])
    for row in list(rows):
        identity_reviews = [d for d in rules.get('productIdentityReviews', []) if d['name'] == row['company_name']]
        reviewed_ids = {d['articleId'] for d in identity_reviews}
        source_ids = {a['id'] for a in row.get('sourceArticles', [])}
        if source_ids and source_ids.issubset(reviewed_ids):
            row['entityType'] = 'product'
            row['identityReview'] = identity_reviews
            for update in row.get('productUpdates', []):
                update['relationship'] = 'unknown'
        disposition = rules.get('excluded', {}).get(row['company_name'])
        if disposition:
            if not disposition.get('url') or not disposition.get('reason'):
                raise ValueError('非公司主体处理缺少证据')
            excluded.append(dict(row, reviewDisposition=disposition, reviewStatus=disposition.get('status', 'confirmed_non_company')))
            rows.remove(row)
            audit['excluded'].append({'name': row['company_name'], **disposition})
            continue
        reason = rules['pending'].get(row['company_name']) or (
            '产品所属公司尚未由文章证实；保留产品，不改变对应新闻分类。'
            if row.get('entityType') == 'product' else None)
        if reason:
            pending.append(dict(row, reviewReason=reason))
            rows.remove(row)
            audit['pending'].append({'name': row['company_name'], 'reason': reason})
    for row in [*rows, *pending]:
        for decision in rules.get('productNameReviews', []):
            if row['company_name'] != decision['company']:
                continue
            for update in row.get('productUpdates', []):
                if update.get('articleId') == decision['articleId'] and update['name'] == decision['from']:
                    update.update(name=decision['to'], originalName=decision['from'], quote=decision['quote'])
            for evidence in row.get('fieldSources', {}).get('product_names', []):
                if evidence.get('articleId') == decision['articleId'] and evidence['value'] == decision['from']:
                    evidence['value'] = decision['to']
            row['product_names'] = [p for p in row['product_names'] if p != decision['from'] or any(u['name'] == p for u in row.get('productUpdates', []))]
        for decision in rules.get('excludedProducts', []):
            if row['company_name'] != decision['company']:
                continue
            row['productUpdates'] = [u for u in row.get('productUpdates', []) if not (u.get('articleId') == decision['articleId'] and u['name'] == decision['name'])]
            row['fieldSources']['product_names'] = [e for e in row['fieldSources'].get('product_names', []) if not (e.get('articleId') == decision['articleId'] and e['value'] == decision['name'])]
            row['product_names'] = [p for p in row['product_names'] if p != decision['name'] or any(u['name'] == p for u in row['productUpdates'])]
        refresh(row)
        for decision in rules.get('productRelationships', []):
            if row['company_name'] != decision['company']:
                continue
            for update in row['productUpdates']:
                if update['name'] == decision['product'] and update.get('articleId') == decision['articleId']:
                    update.update(relationship=decision['relationship'], quote=decision['quote'], reviewedAt=decision.get('reviewedAt', rules['reviewedAt']))
    for row in rows:
        row['updatedAt'] = row['lastSeenAt']
        row['sourceArticles'].sort(key=lambda a: timestamp(a.get('publishedAt')), reverse=True)
    rows.sort(key=lambda r: timestamp(r['updatedAt']), reverse=True)
    decisions = rules['classifications']
    seen = set()
    def review(item):
        decision = decisions.get(item['id'])
        if not decision:
            return
        if fingerprint(item) != decision['fingerprint']:
            if item['id'] not in audit['staleDecisions']:
                audit['staleDecisions'].append(item['id'])
            return
        before = item.get('classification')
        item['classification'] = tag_news.to_display(tx, tag_news.validate(tx, {'category': decision['category'], 'tags': decision.get('tags', {})}))
        item['classificationOrigin'] = decision.get('origin', 'deepseek-review')
        item['classificationReview'] = {'reviewedAt': decision.get('reviewedAt', rules['reviewedAt']), 'reason': decision['reason']}
        if item['id'] not in seen:
            audit['classifications'].append({'id': item['id'], 'title': item['title'], 'url': item.get('url'), 'before': before, 'after': item['classification'], 'reason': decision['reason']})
            seen.add(item['id'])
    for pool in ('all', 'garenaSelected'):
        for item in snapshot.get(pool, {}).get('items', []):
            review(item)
    for view in ('daily', 'weekly'):
        grouped = {}
        for section in snapshot.get(view, {}).get('sections', []):
            for item in section.get('items', []):
                review(item)
                label = (item.get('classification') or {}).get('catLabel') or section['label']
                group = grouped.setdefault(label, dict(section, label=label, items=[]))
                group['items'].append(item)
                group['count'] = len(group['items'])
        if grouped:
            snapshot[view]['sections'] = list(grouped.values())
    overview['stats'].update(companiesTotal=len(rows), productsTotal=sum(len(r['product_names']) for r in rows), pendingEntities=len(pending), excludedEntities=len(excluded))
    overview['coverageNote'] += ' 公司主体与分类已进行抽查；待核实主体单独保留，未计入公司表。'
    validate(overview, tx)
    return overview, snapshot, audit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    source, dest = Path(args.input), Path(args.output)
    if source.resolve() == dest.resolve() or not dest.resolve().is_relative_to(Path('work').resolve()):
        p.error('Use a separate output directory under work/')
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    overview, snapshot, audit = apply(read(source/'company-overview.json'), read(source/'snapshot.json'), read(Path('config/quality_review.json')), tag_news.load_taxonomy('config/taxonomy.json'))
    for name, data in [('company-overview', overview), ('snapshot', snapshot), ('quality-audit', audit)]:
        atomic_write(dest/(name+'.json'), data)
    print(json.dumps({k: len(v) for k, v in audit.items()}))


if __name__ == '__main__':
    main()
