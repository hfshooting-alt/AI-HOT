"""Public article metadata and the independent Garena selection decision.

Callers must supply the already time/source-validated candidate pool. This module
never reads bodies into the public result, runs models, or adopts upstream picks.
"""
import copy


_TEXT_FIELDS = ('id', 'title', 'url', 'mpName', 'collector', 'sourceType',
    'sourceChannel', 'sourcePlatform', 'publishedAt', 'publishedPrecision',
    'discoveredAt', 'evidenceKind', 'contentSha256')


def _strings(value, fields):
    return {key: value[key] for key in fields if isinstance(value.get(key), str)}


def public_time_evidence(value):
    """One public projection after admission; full capture proof stays private."""
    return _strings(value, ('originalText', 'observedAt', 'kind', 'field', 'normalizedAt'))


def _reason(value, fallback):
    return ' '.join(value.split())[:180] if isinstance(value, str) and value.strip() else fallback


def _classification(value):
    if not isinstance(value, dict):
        return None
    result = _strings(value, ('category', 'cat', 'catLabel'))
    if not result.get('category') and not result.get('cat'):
        return None
    if isinstance(value.get('tags'), dict):
        result['tags'] = {k: v for k, v in value['tags'].items() if isinstance(k, str) and isinstance(v, str)}
    if isinstance(value.get('dims'), list):
        result['dims'] = [_strings(v, ('id', 'label', 'value', 'valueId'))
                          for v in value['dims'] if isinstance(v, dict)]
    if isinstance(value.get('autoFallback'), bool):
        result['autoFallback'] = value['autoFallback']
    if isinstance(value.get('autoFilled'), list):
        result['autoFilled'] = [v for v in value['autoFilled'] if isinstance(v, str)]
    return result


def _public_metadata(item):
    public = _strings(item, _TEXT_FIELDS)
    if isinstance(item.get('source'), str):
        public['source'] = item['source']
    elif isinstance(item.get('source'), dict):
        public['source'] = _strings(item['source'], ('name', 'url', 'type', 'id'))
    if isinstance(item.get('sourceRefs'), list):
        public['sourceRefs'] = [_strings(ref, ('collector', 'source', 'url', 'publishedAt'))
                                for ref in item['sourceRefs'] if isinstance(ref, dict)]
    if isinstance(item.get('timeEvidence'), dict):
        public['timeEvidence'] = public_time_evidence(item['timeEvidence'])
    if item.get('metadataOnly') is True:
        public['metadataOnly'] = True
    return public


def build_public_article_library(pool, processed, results=None, enrichments=None):
    """Keep every verified candidate, annotating our own selected/not_selected/pending.

    `processed` is the successfully screened/enriched pool, including any reviewed
    summaries. `results` maps article IDs to relevance
    results. `enrichments` independently maps article IDs to body processing
    results. Missing results mean pending; upstream `selected` is never used.
    """
    results = results or {}
    enrichments = enrichments or {}
    approved = {item['id']: item for item in processed}
    pool_ids = {item['id'] for item in pool}
    if len(approved) != len(processed) or len(pool_ids) != len(pool) or not set(approved).issubset(pool_ids):
        raise ValueError('Article library and selected IDs must be unique and share the same candidate pool')
    library = []
    for item in pool:
        public = _public_metadata(item)
        public.update(contentStatus='awaiting_body' if item.get('metadataOnly') else 'available',
                      classificationStatus='pending', summaryStatus='pending')
        selected = approved.get(item['id'])
        relevance = results.get(item['id']) or {}
        if not isinstance(relevance, dict):
            relevance = {}
        if selected is not None:
            if item.get('metadataOnly'):
                raise ValueError('Metadata-only Manus article cannot become a Garena selection')
            classification = _classification(selected.get('classification'))
            if (not classification or classification.get('autoFallback') is True
                    or not isinstance(selected.get('summary'), str) or not selected['summary'].strip()):
                raise ValueError('Selected article lacks a successful summary/classification')
            public.update(_public_metadata(selected))
            public['summary'] = selected['summary']
            public['summaryOrigin'] = (selected['summaryOrigin']
                if isinstance(selected.get('summaryOrigin'), str) and selected['summaryOrigin'] else 'processed')
            public['classification'] = classification
            public['enrichmentStatus'] = 'complete'
            public.update(classificationStatus='complete', summaryStatus='complete')
            for key in ('editorialReview', 'classificationReview'):
                if isinstance(selected.get(key), dict):
                    public[key] = _strings(selected[key], ('at', 'reviewedAt', 'reason', 'origin'))
            if isinstance(selected.get('classificationOrigin'), str):
                public['classificationOrigin'] = selected['classificationOrigin']
            decision = selected.get('garenaSelection')
            saved_reason = decision.get('reason') if isinstance(decision, dict) else None
            public['garenaSelection'] = {'status': 'selected',
                'reason': _reason(saved_reason or relevance.get('reason'), '已通过 Garena 投资筛选及摘要校验')}
        else:
            public['summary'] = item.get('summary', '') if item.get('collector') == 'aihot' and isinstance(item.get('summary'), str) else ''
            if public['summary']:
                public['summaryOrigin'] = 'upstream'
            if item.get('metadataOnly'):
                status, reason = 'pending', '已核实文章来源与发布时间，正文尚未取得，未进行投资筛选'
            elif relevance.get('status') == 'complete' and relevance.get('relevant') is False:
                status, reason = 'not_selected', _reason(relevance.get('reason'), '未通过 Garena 投资筛选')
            elif relevance.get('status') == 'complete' and relevance.get('relevant') is True:
                status, reason = 'pending', '相关性已通过，摘要或分类尚未通过校验'
            else:
                status, reason = 'pending', 'Garena 投资筛选尚未完成'
            public['garenaSelection'] = {'status': status, 'reason': reason}
            # Classification is independent from the investment decision. Only
            # allowlisted output fields can cross this private/public boundary.
            result = enrichments.get(item['id'])
            if not item.get('metadataOnly') and isinstance(result, dict) and result:
                classification = _classification(result.get('classification'))
                if (classification and classification.get('autoFallback') is False
                        and result.get('enrichmentStatus') in ('complete', 'partial')):
                    classification['tags'] = {}
                    if 'dims' in classification:
                        classification['dims'] = []
                    classification['autoFilled'] = []
                    public.update(classification=classification, classificationStatus='complete')
                elif result.get('modelAttempted') or result.get('enrichmentStatus') in ('failed', 'fallback'):
                    public['classificationStatus'] = 'failed'
                summary = result.get('summary')
                if isinstance(summary, str) and summary.strip() and result.get('summaryStatus') != 'failed':
                    public.update(summary=summary, summaryStatus='complete')
                    if isinstance(result.get('summaryOrigin'), str):
                        public['summaryOrigin'] = result['summaryOrigin']
                    if isinstance(result.get('editorialReview'), dict):
                        public['editorialReview'] = _strings(result['editorialReview'], ('reviewedAt', 'reason', 'origin'))
                elif result.get('modelAttempted') or result.get('enrichmentStatus') in ('failed', 'fallback', 'partial'):
                    public['summaryStatus'] = 'failed'
        library.append(public)
    return copy.deepcopy(library)
