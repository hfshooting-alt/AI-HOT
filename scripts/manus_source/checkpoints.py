"""Recover explicit article checkpoints; prose and incomplete claims are never articles."""
import json
from datetime import datetime, timedelta
import re
from urllib.parse import urlparse
from . import contracts
from .window import BJ


def normalize_article_time(article, observed_at=None):
    """Chinese media wall-clock timestamps are Beijing time; explicit offsets convert."""
    result = dict(article)
    label = result.get('published_time_text') or ''
    if label == '昨天' or re.fullmatch(r'\d+\s*(小时|分钟)前', label):
        observed = observed_at or datetime.now(BJ)
        result['timeEvidence'] = {'originalText': label, 'observedAt': observed.isoformat()}
        if label == '昨天':
            result['published_at'] = (observed - timedelta(days=1)).date().isoformat()
            result['publishedPrecision'] = 'date'
        else:
            match = re.fullmatch(r'(\d+)\s*(小时|分钟)前', label)
            unit = timedelta(hours=1) if match[2] == '小时' else timedelta(minutes=1)
            result['published_at'] = (observed - int(match[1]) * unit).isoformat()
            result['publishedPrecision'] = 'relative'
        result['published_date'] = result['published_at'][:10]
        return result
    value = result.get('published_at')
    if not isinstance(value, str) or not any(c in value for c in ('T', ' ')):
        return result
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        host = (urlparse(result.get('source_home_url') or '').hostname or '').lower()
        chinese = any(host == d or host.endswith('.' + d) for d in
                      ('qq.com', '163.com', 'jiqizhixin.com', 'baijing.cn', 'weixin.qq.com'))
        if dt.tzinfo is None:
            if not chinese:
                return result
            dt = dt.replace(tzinfo=BJ)
        result['published_at'] = dt.astimezone(BJ).isoformat()
    except ValueError:
        pass
    return result


def checkpoint_articles(response):
    for event in response.get('messages', []):
        if event.get('type') != 'assistant_message':
            continue
        text = event.get('assistant_message', {}).get('content', '')
        if not isinstance(text, str):
            continue
        if event.get('assistant_message', {}).get('delivery_kind') == 'result':
            # 普通最终消息不冒充 structured output，仅提取待逐条校验的候选。
            try:
                result = json.loads(text)
                articles = result.get('articles') if isinstance(result, dict) else None
                if isinstance(articles, list):
                    yield from (a for a in articles if isinstance(a, dict))
            except ValueError:
                pass
        for line in text.splitlines():
            if not line.startswith('AIHOT_ARTICLE '):
                continue
            # 平台可能合并相邻进度行；逐个解码完整 JSON，不把尾部说明当文章。
            remaining = line
            while remaining.startswith('AIHOT_ARTICLE '):
                remaining = remaining[len('AIHOT_ARTICLE '):].lstrip()
                try:
                    value, end = json.JSONDecoder().raw_decode(remaining)
                except ValueError:
                    break
                if isinstance(value, dict):
                    yield value
                remaining = remaining[end:].lstrip()


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
    if any(not isinstance(article.get(k), str) or not article[k] for k in required) or article['extraction_status'] != 'complete':
        return False
    if not str(article['article_url']).startswith(('https://', 'http://')):
        return False
    # This mixed-publisher list requires an explicit byline; site branding alone
    # cannot establish that the article was published by the configured newsroom.
    if article['source_platform'] == 'Official Jiqizhixin' and article.get('author') != '机器之心':
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
