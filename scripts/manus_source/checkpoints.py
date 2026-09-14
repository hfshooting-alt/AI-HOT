"""Recover explicit article checkpoints; prose and incomplete claims are never articles."""
import json
from . import contracts


def checkpoint_articles(response):
    for event in response.get('messages', []):
        if event.get('type') != 'assistant_message':
            continue
        text = event.get('assistant_message', {}).get('content', '')
        for line in text.splitlines():
            if not line.startswith('AIHOT_ARTICLE '):
                continue
            try:
                value = json.loads(line[len('AIHOT_ARTICLE '):])
                if isinstance(value, dict):
                    yield value
            except ValueError:
                continue


def partial_payload(group, date, accounts, window, articles, reason):
    payload = {'schema_version': 3 if window else 2, 'source_group': group,
               'target_date': date, 'articles': list(articles), 'source_audits': []}
    if window:
        payload['collectionWindow'] = window
    for name in accounts:
        count = sum(a.get('account_name') == name for a in articles)
        payload['source_audits'].append({'account_name': name,
            'source_status': 'partial' if count else 'failed', 'article_count': count,
            'note': reason})
    contracts.validate_discovery(payload, group, date, accounts)
    return payload


def accept_article(article, group, date, accounts, window, source_specs=None):
    required = ('account_name', 'source_platform', 'source_home_url', 'article_url',
                'title', 'published_date', 'extraction_status')
    if any(not article.get(k) for k in required) or article['extraction_status'] != 'complete':
        return False
    if not str(article['article_url']).startswith(('https://', 'http://')):
        return False
    if source_specs is not None:
        source = next((s for s in source_specs if s['account_name'] == article['account_name']), None)
        if not source or (source['platform'], source['home_url']) != (article['source_platform'], article['source_home_url']):
            return False
    try:
        partial_payload(group, date, accounts, window, [article], 'checkpoint: coverage unverified')
        return True
    except (ValueError, TypeError, KeyError):
        return False
