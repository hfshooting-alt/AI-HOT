"""One anonymous public Tencent author-list request; metadata hints only.

The endpoint/parameters and card fields were observed in the configured public
author pages' channel.js. List time, author binding and one page of ordering do
not prove original publication or complete coverage. Never emit discovery rows.
"""
from datetime import datetime, timedelta
from html import unescape
import hashlib
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .window import BJ, timestamp

TENCENT_LIST = 'https://i.news.qq.com/getSubNewsMixedList'
MAX_BYTES = 1024 * 1024
MAX_SECONDS = 15
MAX_ROWS = 20

# Exact configured account IDs and observed display names, not a fuzzy name match.
_AUTHORS = {
    '游戏葡萄': ('8QMc3npU5YQZujvd', ('游戏葡萄',)),
    '极客公园': ('8QMX2ndU7oYcuTc=', ('极客公园',)),
    '东西文娱': ('8QIf3n5d5YUdsTfQ4gs=', ('东西文娱',)),
    '娱乐资本论': ('8QMd3HZd6IQcvDvR', ('娱乐资本论',)),
    '瑞恩资本': ('8QMY33Zd7YwduQ==', ('瑞恩资本', '瑞恩资本RyanBenCapital')),
    'DeepTech深科技': ('8QMd2Hpe7owfuTk=', ('DeepTech深科技',)),
    'ZPotential': ('8QIf3nxd5YwYvz/c5wM=', ('ZPotential', 'ZPotentials')),
    '华尔街见闻': ('8QMf2HZV5I0a', ('华尔街见闻',)),
    '量子位': ('8QMc3Hle6oMZuDze', ('量子位',)),
    '智东西': ('8QMc2XZf7IAfsD3Z', ('智东西',)),
    '十字路口Crossing': ('8QIf3nxc74IbsT/a5gc=', ('十字路口Crossing',)),
    '投资界': ('8QMf13pd74EYuT7Q', ('投资界',)),
    '赛博禅心': ('8QIf3n9U5I0buzbd4wc=', ('赛博禅心',)),
    '新智元': ('8QMc2Hpa6oYVujjQ', ('新智元',)),
}


class SeedError(ValueError):
    """A fixed diagnostic code, never raw headers, exceptions or response bodies."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SeedError('redirect_rejected')


def _fetch(request, timeout_seconds, max_bytes):
    deadline = time.monotonic() + timeout_seconds
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout_seconds) as response:
        chunks, remaining = [], max_bytes + 1
        while remaining:
            left = deadline - time.monotonic()
            if left <= 0:
                raise SeedError('request_timeout')
            # Bound each socket read by the remaining total deadline, including
            # time already spent connecting. No environment proxy credentials.
            sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            if sock is not None:
                sock.settimeout(left)
            part = response.read1(min(65536, remaining))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        if time.monotonic() >= deadline:
            raise SeedError('request_timeout')
        return response.status, response.geturl(), b''.join(chunks)


def _clean(value, limit=500):
    return ' '.join(unescape(value).split())[:limit] if isinstance(value, str) else ''


def _configured(source):
    if not isinstance(source, dict) or source.get('platform') != 'Tencent News':
        return None
    name = source.get('account_name')
    known = _AUTHORS.get(name) if isinstance(name, str) else None
    if not known or not isinstance(source.get('home_url'), str):
        return None
    try:
        home = urlsplit(source['home_url'])
        if (home.scheme != 'https' or home.netloc != 'news.qq.com' or home.fragment
                or not re.fullmatch(r'/omn/author/[A-Za-z0-9%+=]+', home.path)):
            return None
        query = parse_qs(home.query, keep_blank_values=True)
        if query and query not in ({'tab': ['om_article']}, {'tab': ['om_index']}):
            return None
        if unquote(home.path.rsplit('/', 1)[1]) != known[0]:
            return None
    except ValueError:
        return None
    return known


def _article_url(value, ident):
    if not isinstance(value, str):
        return ''
    try:
        parts = urlsplit(value)
        if parts.scheme != 'https' or parts.netloc not in ('view.inews.qq.com', 'news.qq.com'):
            return ''
        paths = (f'/a/{ident}',) if parts.netloc == 'view.inews.qq.com' else (f'/rain/a/{ident}', f'/a/{ident}')
        if parts.path not in paths:
            return ''
        # Preserve the returned public path, never synthesize a URL from an ID.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    except ValueError:
        return ''


def _absolute(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?', value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (parsed.replace(tzinfo=BJ) if parsed.tzinfo is None else parsed.astimezone(BJ))
    except ValueError:
        return None


def _time_hint(row, observed, start, end):
    labels = [_clean(row.get('publish_time'), 120), _clean(row.get('time'), 120)]
    absolutes = [(label, _absolute(label), 'list_absolute_time') for label in labels if _absolute(label)]
    raw_epoch = row.get('timestamp')
    if type(raw_epoch) is int and 946684800 <= raw_epoch <= 4102444800:
        absolutes.append((str(raw_epoch), datetime.fromtimestamp(raw_epoch, BJ), 'list_timestamp'))
    if absolutes:
        label, at, basis = absolutes[0]
        # Minute and second displays may differ within a minute. Larger conflicts
        # remain unresolved; never let a relative '昨天' override an absolute date.
        conflict = any(abs((other - at).total_seconds()) >= 60 for _, other, _ in absolutes)
        relation = ('unknown' if conflict else 'before_window' if at < start
                    else 'after_window' if at >= end else 'within_window')
        return label, relation, basis, at.isoformat(), conflict
    for label in labels:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', label):
            try:
                day = datetime.strptime(label, '%Y-%m-%d').replace(tzinfo=BJ)
            except ValueError:
                continue
            relation = ('before_window' if day + timedelta(days=1) <= start else
                        'after_window' if day >= end else 'overlaps_boundary')
            return label, relation, 'list_absolute_date', None, False
    label = next((label for label in labels if label), '')
    if label == '昨天':
        day = (observed - timedelta(days=1)).date()
        relation = ('yesterday_exception_hint' if day == start.date() else
                    'before_window' if day < start.date() else 'after_window')
        return label, relation, 'relative_yesterday_label', None, False
    return label, 'unknown', 'unverified_list_label', None, False


def _challenge(body):
    if body.lstrip().startswith((b'{', b'[')):
        return False
    text = body.decode('utf-8', errors='replace').lower()
    title = re.search(r'<title\b[^>]*>(.*?)</title\s*>', text, re.S)
    markers = ('安全验证', '人机验证', '滑动验证', 'just a moment', 'verify you are human', 'captcha')
    return bool((title and any(marker in title[1] for marker in markers))
                or '/cdn-cgi/challenge-platform/' in text or 'cf-chl-' in text)


def build_tencent_seed(source, window, *, transport=None, now_fn=None):
    """Return at most 20 list hints from one GET, with no retries or detail fetch.

    transport(request, timeout_seconds, max_bytes) -> (status, final_url, bytes)
    is an offline seam. The caller owns persistence and reuse of observations.
    """
    output = {'schemaVersion': 1, 'hintOnly': True, 'coverageComplete': False,
        'identityVerified': False, 'status': 'unsupported', 'requestsAttempted': 0,
        'candidates': [], 'observations': [], 'pages': [],
        'warnings': ['manus_original_time_and_identity_check_required',
                     'one_page_order_and_window_coverage_unverified',
                     'no_candidates_does_not_mean_no_articles']}
    known = _configured(source)
    if known is None:
        if isinstance(source, dict) and source.get('platform') == 'Tencent News':
            output.update(status='unavailable', stopReason='source_configuration_mismatch')
        return output
    start, end = timestamp(window['start']), timestamp(window['end'])
    if window.get('timezone') != 'Asia/Shanghai' or end - start != timedelta(days=1):
        raise ValueError('Tencent seed needs a fixed 24-hour Beijing window')
    output['source'] = {key: source[key] for key in ('account_name', 'platform', 'home_url')}
    output['collectionWindow'] = dict(window)
    params = {'offset_info': '', 'guestSuid': known[0], 'tabId': 'om_article', 'caller': 1, 'from_scene': 103}
    url = TENCENT_LIST + '?' + urlencode(params)
    request = Request(url, method='GET', headers={'User-Agent': 'AI-HOT-source-preflight/1.0',
        'Accept': 'application/json', 'Accept-Encoding': 'identity'})
    try:
        output['requestsAttempted'] = 1
        try:
            status, final_url, body = (transport or _fetch)(request, MAX_SECONDS, MAX_BYTES)
        except SeedError:
            raise
        except HTTPError as exc:
            raise SeedError('redirect_rejected' if 300 <= exc.code < 400 else f'http_{exc.code}') from None
        except Exception:
            raise SeedError('network_unavailable') from None
        if final_url != url:
            raise SeedError('redirect_rejected')
        if status != 200:
            raise SeedError(f'http_{status}' if type(status) is int else 'http_error')
        if not isinstance(body, bytes) or len(body) > MAX_BYTES:
            raise SeedError('response_size_limit')
        if _challenge(body):
            raise SeedError('security_verification')
        try:
            payload = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise SeedError('list_schema_unverified') from None
        if (not isinstance(payload, dict) or type(payload.get('ret')) is not int or payload['ret'] != 0
                or not isinstance(payload.get('newslist'), list) or len(payload['newslist']) > MAX_ROWS):
            raise SeedError('list_schema_unverified')
        observed = (now_fn or (lambda: datetime.now(BJ)))()
        if not isinstance(observed, datetime) or observed.tzinfo is None:
            raise SeedError('observation_time_unverified')
        observed = observed.astimezone(BJ)
        output['responseSha256'] = hashlib.sha256(body).hexdigest()
        output['pages'].append({'page': 1, 'rowCount': len(payload['newslist']), 'observedAt': observed.isoformat(),
                                'sha256': output['responseSha256']})
        seen, rejected, times = set(), 0, []
        for index, raw in enumerate(payload['newslist']):
            if not isinstance(raw, dict):
                output['observations'].append({'listIndex': index, 'metadataStatus': 'rejected',
                                              'rejectionReasons': ['row_shape_unverified']})
                rejected += 1
                continue
            ident, title = _clean(raw.get('id'), 80), _clean(raw.get('title'))
            card = raw.get('card') if isinstance(raw.get('card'), dict) else {}
            link = raw.get('link_info') if isinstance(raw.get('link_info'), dict) else {}
            names = [_clean(raw.get('chlname'), 200), _clean(card.get('chlname'), 200)]
            card_suid = _clean(card.get('suid'), 200)
            article_url = _article_url(raw.get('url') or link.get('url'), ident)
            label, relation, basis, displayed, conflict = _time_hint(raw, observed, start, end)
            reasons = []
            if not re.fullmatch(r'[A-Za-z0-9]{8,40}', ident) or not title:
                reasons.append('article_identity_unverified')
            if not article_url:
                reasons.append('article_url_unverified')
            if card_suid != known[0] or not all(names) or any(name not in known[1] for name in names):
                reasons.append('source_binding_unverified')
            item = {'id': ident, 'title': title, 'url': article_url, 'listIndex': index,
                'listTimeText': label, 'listObservedAt': observed.isoformat(),
                'rawPublishTime': _clean(raw.get('publish_time'), 120), 'rawTime': _clean(raw.get('time'), 120),
                'rawTimestamp': raw.get('timestamp') if type(raw.get('timestamp')) is int else None,
                'rawChlname': names[0], 'cardChlname': names[1], 'cardSuid': card_suid,
                'windowHint': relation, 'timeBasis': basis, 'originalPublicationVerified': False,
                'requiresManusVerification': True, 'metadataStatus': 'rejected' if reasons else 'hint',
                'rejectionReasons': reasons}
            if displayed:
                item['listDisplayedAt'] = displayed
            if conflict:
                item['listTimeConflict'] = True
            output['observations'].append(item)
            if reasons:
                rejected += 1
                continue
            if displayed and not conflict:
                times.append(timestamp(displayed))
            if article_url in seen:
                item['duplicateListRow'] = True
                continue
            seen.add(article_url)
            if relation not in ('before_window', 'after_window'):
                output['candidates'].append(item)
        priority = {'within_window': 0, 'yesterday_exception_hint': 1, 'overlaps_boundary': 2, 'unknown': 3}
        output['candidates'].sort(key=lambda item: priority[item['windowHint']])
        output.update(status='partial' if rejected else 'available', stopReason='one_page_limit', rejectedRows=rejected)
        if rejected:
            output['warnings'].append('list_rows_rejected')
        output['boundary'] = {'coverageVerified': False, 'ordering': 'unverified',
            'hasNext': payload.get('hasNext') if type(payload.get('hasNext')) in (bool, int) else None,
            'observedListOrder': ('insufficient_sample' if len(times) < 2 else 'out_of_order'
                if any(a < b for a, b in zip(times, times[1:])) else 'nonincreasing_sample'),
            'reason': 'one_page_limit_and_unverified_original_time_or_pinning'}
    except SeedError as exc:
        code = str(exc)
        output.update(status='blocked' if code in ('security_verification', 'http_401', 'http_403', 'http_429')
                      else 'unavailable', stopReason=code)
    return output
