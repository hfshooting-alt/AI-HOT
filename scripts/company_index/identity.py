"""应用已审阅的公司归属与官网补全；不调用网络或模型。"""
import copy
import hashlib
import json
from pathlib import Path

from .config import SCALAR_FIELDS
from .entities import entity_id
from funding.companies import normalize_company_key

RULES_PATH = Path(__file__).resolve().parents[2] / 'config' / 'company_research.json'


def apply_reviewed_research(companies, rules=None):
    if rules is None:
        rules = json.loads(RULES_PATH.read_text(encoding='utf-8')) if RULES_PATH.exists() else {'records': []}
    rows = copy.deepcopy(companies)
    for rule in rules.get('records', []):
        if rule.get('reviewed') is not True or not rules.get('checkedAt'):
            raise ValueError('归属修正必须先审阅并记录核验时间')
        source = next((c for c in rows if c['company_name'] == rule['record_name']), None)
        owner = rule.get('owner_company')
        target = next((c for c in rows if c['company_name'] == owner), None) if owner else source
        if source is None and target is None:
            continue
        if source is not None and owner and source['company_name'] != owner:
            if target is None:
                target = copy.deepcopy(source)
                target.update(id=entity_id(normalize_company_key(owner)), company_name=owner, aliases=[],
                              **{f: None for f in SCALAR_FIELDS}, fieldSources={}, product_names=[])
                rows.append(target)
            # 品牌资料单独保留，不把产品成立年份/负责人当成母公司字段。
            target.setdefault('brandProfiles', {})[source['company_name']] = source
            target['product_names'] = list(dict.fromkeys([*target['product_names'], source['company_name'], *source['product_names']]))
            product_evidence = target['fieldSources'].setdefault('product_names', [])
            for evidence in source.get('fieldSources', {}).get('product_names', []):
                if not any(e['articleId'] == evidence['articleId'] and e['value'] == evidence['value'] for e in product_evidence):
                    product_evidence.append(evidence)
            existing = {a['id'] for a in target['sourceArticles']}
            target['sourceArticles'].extend(a for a in source['sourceArticles'] if a['id'] not in existing)
            target['lastSeenAt'] = max(target['lastSeenAt'], source['lastSeenAt'])
            target['firstSeenAt'] = min(target['firstSeenAt'], source['firstSeenAt'])
            rows.remove(source)
        for fact in rule.get('facts', []):
            field, value = fact['field'], fact['value']
            if field == 'owner_company':
                field = 'company_name'
            if field not in ('company_name', 'product_names', *SCALAR_FIELDS):
                raise ValueError('不支持的补全字段')
            if not fact.get('quote') or not fact.get('url', '').startswith('https://'):
                raise ValueError('已审阅补全缺少来源')
            if field in SCALAR_FIELDS:
                if not target.get(field):
                    target[field] = value
            elif field == 'product_names' and value not in target['product_names']:
                target['product_names'].append(value)
            evidence = dict(value=value, articleId='research:' + hashlib.sha256(fact['url'].encode()).hexdigest()[:16],
                            url=fact['url'], title=fact['title'], publishedAt='', sourceName='官网资料核验',
                            origin='research', quote=fact['quote'], checkedAt=rules['checkedAt'])
            bucket = target['fieldSources'].setdefault(field, [])
            if not any(e['articleId'] == evidence['articleId'] and e['value'] == value for e in bucket):
                bucket.append(evidence)
    return rows
