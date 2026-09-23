"""Exact evidence-bound editorial projections; never mutate captured responses."""
import copy
import hashlib
import json
from pathlib import Path
from manus_source.source_urls import tencent_article_id

PATH = Path(__file__).resolve().parents[2] / 'config/direct_content_review.json'


def apply(source, items, rules=None):
    rules = rules if rules is not None else json.loads(PATH.read_text(encoding='utf-8'))
    if rules.get('schemaVersion') != 1:
        raise ValueError('Unsupported direct editorial rules')
    result = copy.deepcopy(items)
    for rule in rules.get('reviews', []):
        if not rule.get('reviewedAt') or rule.get('action') != 'withhold_body':
            raise ValueError('Unreviewed or unsupported direct content correction')
        for item in result:
            same_url = item['url'] == rule['url'] or (tencent_article_id(item['url']) is not None
                and tencent_article_id(item['url']) == tencent_article_id(rule['url']))
            if (source['account_name'] == rule['source'] and same_url and item['title'] == rule['title']
                    and hashlib.sha256(item['content_text'].encode()).hexdigest() == rule['contentSha256']):
                item['content_text'] = ''
                item['validation'].update(bodyStatus='editorial_withheld',
                    contentReview={'reviewedAt': rule['reviewedAt'], 'reason': rule['reason'],
                                   'originalContentSha256': rule['contentSha256']})
    return result
