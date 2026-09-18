"""应用已审阅的公司归属与官网补全；不调用网络或模型。"""
import copy
import hashlib
import json
from pathlib import Path

from .config import SCALAR_FIELDS
from .entities import timestamp
from .entities import entity_id
from funding.companies import normalize_company_key, _country_to_region_label

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
        if any(f.get('verificationStatus') == 'provisional' and f.get('field') in ('owner_company', 'company_name', 'product_names') for f in rule.get('facts', [])):
            raise ValueError('暂定资料不能合并主体或确认产品归属')
        # Use the same name normalization as entity IDs. Spelling variants such
        # as Z.ai / Z .AI must reuse the existing entity instead of appending a
        # second row with the same ID. Do not match product aliases here.
        target = next((c for c in rows if normalize_company_key(c['company_name'])
                       == normalize_company_key(owner)), None) if owner else source
        if target is not None and owner and target['company_name'] != owner:
            target['aliases'] = list(dict.fromkeys([*target.get('aliases', []), target['company_name']]))
            target['company_name'] = owner
        if source is None and target is None:
            continue
        for candidate in rule.get('candidateOwners', []):
            if (not candidate.get('name') or not candidate.get('reason') or not candidate.get('quote')
                    or not candidate.get('url', '').startswith('https://')):
                raise ValueError('候选归属缺少来源或未决问题')
            if source is not None:
                bucket = source.setdefault('candidateOwners', [])
                if candidate not in bucket:
                    bucket.append(copy.deepcopy(candidate))
        source_articles = copy.deepcopy(source.get('sourceArticles', [])) if source else []
        owned = rule.get('owned_products', [])
        owner_fact = next((f for f in rule.get('facts', []) if f.get('field') == 'owner_company'
                           and f.get('value') == owner and f.get('quote') and f.get('url', '').startswith('https://')), None)
        if owned and not owner_fact:
            raise ValueError('自有产品补全缺少归属证据')
        if source is not None and owner and source is not target:
            if target is None:
                target = copy.deepcopy(source)
                target.update(id=entity_id(normalize_company_key(owner)), company_name=owner, aliases=[],
                              **{f: None for f in SCALAR_FIELDS}, fieldSources={}, product_names=[], productUpdates=[])
                rows.append(target)
            target['entityType'] = 'company'
            # 品牌资料单独保留，不把产品成立年份/负责人当成母公司字段。
            target.setdefault('brandProfiles', {})[source['company_name']] = source
            source_products = [] if rule.get('source_kind') in ('division', 'company_alias') else [source['company_name']]
            target['aliases'] = list(dict.fromkeys([*target.get('aliases', []), source['company_name'], *source.get('aliases', [])]))
            target['product_names'] = list(dict.fromkeys([*target['product_names'], *source_products, *source['product_names']]))
            target.setdefault('productUpdates', []).extend(u for u in source.get('productUpdates', []) if u not in target.get('productUpdates', []))
            product_evidence = target['fieldSources'].setdefault('product_names', [])
            for evidence in source.get('fieldSources', {}).get('product_names', []):
                if not any(e['articleId'] == evidence['articleId'] and e['value'] == evidence['value'] for e in product_evidence):
                    product_evidence.append(evidence)
            existing = {a['id'] for a in target['sourceArticles']}
            target['sourceArticles'].extend(a for a in source['sourceArticles'] if a['id'] not in existing)
            target['lastSeenAt'] = max((target['lastSeenAt'], source['lastSeenAt']), key=timestamp)
            target['firstSeenAt'] = min((target['firstSeenAt'], source['firstSeenAt']), key=timestamp)
            rows.remove(source)
        if target is not None and rule.get('owner_entity_type'):
            kind = rule['owner_entity_type']
            evidence = rule.get('entity_type_evidence') or {}
            if (kind not in ('foundation', 'open_source_organization')
                    or not evidence.get('quote') or not evidence.get('url', '').startswith('https://')
                    or not evidence.get('checkedAt')):
                raise ValueError('非商业主体类型缺少已核实证据')
            target['entityType'] = kind
            target['entityTypeEvidence'] = copy.deepcopy(evidence)
            target.pop('reviewReason', None)
        for fact in rule.get('facts', []):
            field, value = fact['field'], fact['value']
            if field == 'owner_company':
                field = 'company_name'
            if field not in ('company_name', 'product_names', *SCALAR_FIELDS):
                raise ValueError('不支持的补全字段')
            if not fact.get('quote') or not fact.get('url', '').startswith('https://'):
                raise ValueError('已审阅补全缺少来源')
            if field in SCALAR_FIELDS:
                if fact.get('verificationStatus') == 'provisional':
                    if not fact.get('reason'):
                        raise ValueError('暂定资料需要说明判断依据与未决问题')
                    # 暂定值只补空白，不能覆盖任何既有值。
                    if target.get(field) and target[field] != value:
                        continue
                    if any(e.get('value') == value and e.get('verificationStatus') != 'provisional'
                           for e in target.get('fieldSources', {}).get(field, [])):
                        continue
                if target.get(field) and target[field] != value and fact.get('replace') is not True:
                    # 保留原值时，不把相矛盾的官网事实挂成该值的证据。
                    continue
                if not target.get(field) or fact.get('replace') is True:
                    target[field] = value
                if field == 'country':
                    target.setdefault('dims', {})['国家/地区'] = _country_to_region_label(value)
            elif field == 'product_names' and value not in target['product_names']:
                target['product_names'].append(value)
            evidence = dict(value=value, articleId='research:' + hashlib.sha256(fact['url'].encode()).hexdigest()[:16],
                            url=fact['url'], title=fact['title'], publishedAt='', sourceName='公开资料核验',
                            origin='research', quote=fact['quote'], checkedAt=fact.get('checkedAt') or rules['checkedAt'])
            for key in ('dateBasis', 'legalEntity', 'asOf', 'countryBasis', 'verificationStatus', 'reason'):
                if fact.get(key):
                    evidence[key] = fact[key]
            if fact.get('origin') == 'article':
                if not fact.get('articleId'):
                    raise ValueError('报道归属修正缺少文章标识')
                evidence.update(origin='article', articleId=fact['articleId'],
                                publishedAt=fact.get('publishedAt', ''), sourceName=fact.get('sourceName', '报道内容复核'))
            bucket = target['fieldSources'].setdefault(field, [])
            if not any(e['articleId'] == evidence['articleId'] and e['value'] == value and e.get('verificationStatus') == evidence.get('verificationStatus') for e in bucket):
                bucket.append(evidence)
        # Research proves ownership; retain the original report date and link.
        # Do not change integrations belonging to other company records.
        for name in owned:
            updates = target.setdefault('productUpdates', [])
            for article in source_articles:
                if not any(u['name'] == name and u.get('articleId') == article['id'] for u in updates):
                    updates.append(dict(name=name, relationship='unknown', quote='', articleId=article['id'],
                                        **{k: article.get(k, '') for k in ('url', 'title', 'publishedAt')}))
            for update in updates:
                if update['name'] == name and update.get('relationship') == 'unknown':
                    update.update(relationship='owned', ownershipEvidence=copy.deepcopy(owner_fact))
    for rec in rows:
        rec['updatedAt'] = rec.get('lastSeenAt') or ''
        rec.get('sourceArticles', []).sort(key=lambda a: timestamp(a.get('publishedAt')), reverse=True)
    return sorted(rows, key=lambda r: timestamp(r.get('lastSeenAt')), reverse=True)
