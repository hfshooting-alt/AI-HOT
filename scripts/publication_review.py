"""Apply dated, title-bound primary-source publication checks without network calls."""
import json
import hashlib
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit


def canonical(url):
    p = urlsplit(url)
    return (p.hostname or '').lower(), p.path.rstrip('/')


def review(items, window, rules=None):
    if rules is None:
        path = Path(__file__).resolve().parents[1] / 'config/news_publication_review.json'
        rules = json.loads(path.read_text(encoding='utf-8'))
    accepted, isolated = [], []
    for item in items:
        rule = next((r for r in rules['records'] if canonical(r['url']) == canonical(item['url'])
                     and r['title'] == item['title'] and (not r.get('sourceHash') or r['sourceHash'] ==
                         hashlib.sha256(item.get('content_text','').encode()).hexdigest())), None)
        if rule and rule.get('evidence') and rule.get('checkedAt') and rule['originalPublishedDate'] < window['start'][:10]:
            isolated.append({'id': item['id'], 'title': item['title'], 'url': item['url'],
                             'stage': 'publication_time', 'reason': rule['reason'],
                             'originalPublishedDate': rule['originalPublishedDate'],
                             'checkedAt': rule['checkedAt'], 'evidence': rule['evidence']})
        else:
            hint = re.search(r'/(20\d{2})/(\d{2})/(\d{2})/', urlsplit(item['url']).path + '/')
            day = None
            if hint:
                try:
                    day = date(*map(int, hint.groups())).isoformat()
                except ValueError:
                    pass
            if day and day < window['start'][:10]:
                isolated.append({'id': item['id'], 'title': item['title'], 'url': item['url'],
                    'stage': 'publication_time', 'reason': '链接路径含窗口前日期，原文时间待核验；不把聚合收录时间当成原文发布时间。',
                    'urlDateHint': day, 'verificationStatus': 'unverified'})
            else:
                accepted.append(item)
    return accepted, isolated
