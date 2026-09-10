"""Replay reviewed decisions against a candidate directory, without API calls.

Original model artifacts remain untouched; outputs and audit are written separately.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import tag_news
from company_index.entities import timestamp
from company_index.identity import apply_reviewed_research
from company_index.output import atomic_write, validate


def fingerprint(item):
    return hashlib.sha256(json.dumps([item.get('title'), item.get('summary')], ensure_ascii=False).encode()).hexdigest()


def apply(overview, snapshot, rules, tx):
    overview, snapshot = copy.deepcopy(overview), copy.deepcopy(snapshot)
    rows = overview['companies'] = apply_reviewed_research(overview['companies'])
    audit = {'merged': [], 'pending': [], 'excluded': [], 'classifications': [], 'staleDecisions': []}
    for source, owner in rules['aliases'].items():
        src = next((r for r in rows if r['company_name'] == source), None)
        dst = next((r for r in rows if r['company_name'] == owner), None)
        if not src or not dst:
            continue
        dst.setdefault('reviewMergedRecords', {})[source] = copy.deepcopy(src)
        dst['aliases'] = list(dict.fromkeys(dst['aliases'] + [source] + src['aliases']))
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
        disposition = rules.get('excluded', {}).get(row['company_name'])
        if disposition:
            if not disposition.get('url') or not disposition.get('reason'):
                raise ValueError('非公司主体处理缺少证据')
            excluded.append(dict(row, reviewDisposition=disposition, reviewStatus='confirmed_non_company'))
            rows.remove(row)
            audit['excluded'].append({'name': row['company_name'], **disposition})
            continue
        reason = rules['pending'].get(row['company_name'])
        if reason:
            pending.append(dict(row, reviewReason=reason))
            rows.remove(row)
            audit['pending'].append({'name': row['company_name'], 'reason': reason})
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
        item['classificationOrigin'] = 'deepseek-review'
        item['classificationReview'] = {'reviewedAt': rules['reviewedAt'], 'reason': decision['reason']}
        if item['id'] not in seen:
            audit['classifications'].append({'id': item['id'], 'title': item['title'], 'url': item.get('url'), 'before': before, 'after': item['classification'], 'reason': decision['reason']})
            seen.add(item['id'])
    for item in snapshot.get('all', {}).get('items', []):
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
