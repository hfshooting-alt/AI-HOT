"""Bounded anonymous Baijing list hints for Manus; never a discovery result.

The public list's add_time is a display label (including '1 天前'), not a
documented original-publication field. Preserve it and the observation time.
Detail header times can narrow a hint to the requested window, but Manus must
still verify original publication, source identity and complete coverage.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .window import BJ, timestamp

BAIJING_HOME = 'https://www.baijing.cn/article/'
BAIJING_LIST = 'https://www.baijing.cn/index/ajax/get_article/'
MAX_REQUESTS = 6
MAX_BYTES = 1024 * 1024
MAX_SECONDS = 60
_DETAIL_URL = re.compile(r'https://www\.baijing\.cn/article/[1-9][0-9]{0,11}\Z')
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class SeedError(ValueError):
    """Only a fixed diagnostic code; no response bodies, headers or credentials."""


def compact_source_seed(seed, max_candidates=3):
    """Project up to three useful hints; omitted rows still require discovery.

    Detail headers narrow a window hint but never establish original publication
    or source identity. Preserve order within each evidence tier and never
    mutate the full private observations used for audit or subsequent replay.
    """
    if type(max_candidates) is not int or not 0 <= max_candidates <= 3:
        raise ValueError('max_candidates must be between 0 and 3')
    if not isinstance(seed, dict):
        raise ValueError('seed must be an object')
    candidates = seed.get('candidates', [])
    if not isinstance(candidates, list) or any(not isinstance(row, dict) for row in candidates):
        raise ValueError('seed candidates must be objects')

    def priority(row):
        hint = row.get('windowHint')
        header = row.get('headerTime')
        if hint == 'within_window' and isinstance(header, dict) and header.get('displayedAt'):
            return 0
        if hint in ('within_window', 'likely_within_window', 'yesterday_exception_hint'):
            return 1
        if hint == 'overlaps_boundary':
            return 2
        if hint in (None, 'unknown'):
            return 3
        return 4

    keys = ('status', 'hintOnly', 'coverageComplete', 'identityVerified', 'stopReason')
    brief = {key: deepcopy(seed[key]) for key in keys if key in seed}
    fields = ('title', 'url', 'listTimeText', 'listObservedAt', 'windowHint')
    header_fields = ('displayedTimeText', 'displayedAt')
    selected = sorted(candidates, key=priority)[:max_candidates]
    brief['candidates'] = []
    for row in selected:
        item = {key: deepcopy(row[key]) for key in fields if key in row}
        if isinstance(row.get('headerTime'), dict):
            item['headerTime'] = {key: deepcopy(row['headerTime'][key])
                                  for key in header_fields if key in row['headerTime']}
        brief['candidates'].append(item)
    brief['totalCandidateHints'] = len(candidates)
    brief['additionalCandidatesOmitted'] = len(candidates) - len(selected)
    brief['omittedCandidatesExcluded'] = False
    brief['omissionNote'] = '仅压缩提示；省略项未被排除，仍须按配置来源发现与核验，不能据此宣称完整覆盖。'
    return brief


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SeedError('redirect_rejected')


def _fetch(request, timeout_seconds, max_bytes):
    # No proxy credentials, cookie jar, authentication handler, retries or JS.
    deadline = time.monotonic() + timeout_seconds
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout_seconds) as response:
        chunks, remaining = [], max_bytes + 1
        while remaining:
            if time.monotonic() >= deadline:
                raise SeedError('request_timeout')
            # read1 returns after at most one underlying read, so a slowly
            # streaming response cannot indefinitely postpone the deadline
            # check by keeping a full read(max_bytes) incomplete.
            part = response.read1(min(65536, remaining))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        return response.status, response.geturl(), b''.join(chunks)


def _clean(value, limit=500):
    return ' '.join(unescape(value).split())[:limit] if isinstance(value, str) else ''


def _same_title(left, right):
    return re.sub(r'\s+', '', unescape(left)) == re.sub(r'\s+', '', unescape(right))


def _challenge(text):
    # A news title about CAPTCHA is not a browser challenge. JSON schema is
    # checked separately; challenge pages are HTML, never executed here.
    if text.lstrip().startswith(('{', '[')):
        return False
    title = re.search(r'<title\b[^>]*>(.*?)</title\s*>', text, re.I | re.S)
    markers = ('安全验证', '人机验证', '滑动验证', 'just a moment', 'verify you are human', 'captcha')
    if title and any(marker in title[1].lower() for marker in markers):
        return True
    return ('cf-chl-' in text or '/cdn-cgi/challenge-platform/' in text
            or (len(text) < 20000 and any(marker in text.lower() for marker in markers)))


class _Header(HTMLParser):
    """Only article mod-head/h1/timeago; never nav, recommendations or comments."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.head_depth, self.capture = [], None, None
        self.titles, self.times = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in _VOID:
            return
        self.stack.append(tag)
        if self.head_depth is None and 'mod-head' in (attrs.get('class') or '').split():
            self.head_depth = len(self.stack)
        if self.head_depth is not None and self.capture is None:
            if tag == 'h1' or (tag == 'time' and 'timeago' in (attrs.get('class') or '').split()):
                self.capture = [len(self.stack), tag, []]

    def handle_data(self, value):
        if self.capture:
            self.capture[2].append(value)

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        if self.capture and depth <= self.capture[0]:
            target = self.titles if self.capture[1] == 'h1' else self.times
            target.append(_clean(''.join(self.capture[2])))
            self.capture = None
        if self.head_depth is not None and depth <= self.head_depth:
            self.head_depth = None
        del self.stack[depth - 1:]


def parse_baijing_detail(text, expected_title):
    """Return the site's displayed minute, never an inferred original timestamp."""
    if _challenge(text):
        raise SeedError('security_verification')
    parser = _Header()
    parser.feed(text)
    titles, times = set(parser.titles), set(parser.times)
    if len(titles) != 1 or not _same_title(next(iter(titles)), expected_title):
        raise SeedError('detail_title_unverified')
    if len(times) != 1:
        raise SeedError('detail_time_unverified')
    raw = next(iter(times))
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', raw):
        raise SeedError('detail_time_unverified')
    try:
        value = datetime.strptime(raw, '%Y-%m-%d %H:%M').replace(tzinfo=BJ)
    except ValueError:
        raise SeedError('detail_time_unverified') from None
    return {'displayedTimeText': raw, 'displayedAt': value.isoformat(),
            'precision': 'minute', 'basis': 'article_header_timeago',
            'originalPublicationVerified': False}


def _list_range(label, observed):
    # A deliberately broad estimate, not the publication timestamp. In real
    # samples "1 天前" covers both yesterday and the day before yesterday.
    match = re.fullmatch(r'(\d+)\s*(分钟|小时|天)前', label)
    if match and 0 <= int(match[1]) <= 365:
        unit = {'分钟': timedelta(minutes=1), '小时': timedelta(hours=1), '天': timedelta(days=1)}[match[2]]
        earliest = observed - (int(match[1]) + 1) * unit
        latest = observed - max(0, int(match[1]) - 1) * unit
        return {'earliest': earliest.isoformat(), 'latest': latest.isoformat(), 'approximate': True}
    return None


def _relation(earliest, latest, start, end):
    if latest <= start:
        return 'before_window'
    if earliest >= end:
        return 'after_window'
    if earliest >= start and latest <= end:
        return 'within_window'
    return 'overlaps_boundary'


def _parse_list(text, page, observed, start, end):
    if _challenge(text):
        raise SeedError('security_verification')
    try:
        payload = json.loads(text)
        rows = payload['data']['article_list']
        if payload.get('success') is not True or type(payload.get('code')) is not int or payload['code'] != 0:
            raise ValueError()
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise SeedError('list_schema_unverified') from None
    hints, rejected = [], 0
    for row in rows:
        if not isinstance(row, dict):
            rejected += 1
            continue
        ident = str(row.get('id', ''))
        title = _clean(row.get('title'))
        if not re.fullmatch(r'[1-9][0-9]{0,11}', ident) or not title:
            rejected += 1
            continue
        label = _clean(row.get('add_time'), 120)
        span = _list_range(label, observed)
        hint = {'title': title, 'url': BAIJING_HOME + ident, 'page': page,
                'listTimeText': label, 'listObservedAt': observed.isoformat(),
                'timeBasis': 'unverified_list_add_time', 'originalPublicationVerified': False,
                'windowHint': 'unknown', 'requiresManusVerification': True}
        if span:
            hint['listTimeEstimate'] = span
            hint['windowHint'] = _relation(timestamp(span['earliest']), timestamp(span['latest']), start, end)
        if row.get('sort') not in (None, 0, '0') or row.get('is_top') or row.get('top'):
            hint['possiblyPinned'] = True
        hints.append(hint)
    return hints, len(rows), rejected


def build_source_seed(source, window, *, transport=None, max_pages=3, max_details=3,
                      timeout_seconds=10, max_bytes=MAX_BYTES, now_fn=None):
    """Return hints/observations only; no source_status or discovery articles.

    transport(request, timeout_seconds, max_bytes) -> (status, final_url, bytes)
    is an offline test seam. Supported public sources remain hints-only.
    Network attempts include failures, with at most six, no retry or redirect.
    """
    if isinstance(source, dict) and source.get('platform') == 'Tencent News':
        from .tencent_seeds import build_tencent_seed
        return build_tencent_seed(source, window, transport=transport, now_fn=now_fn)
    output = {'schemaVersion': 1, 'hintOnly': True, 'coverageComplete': False,
        'identityVerified': False, 'status': 'unsupported', 'requestsAttempted': 0,
        'candidates': [], 'observations': [], 'excludedByHeaderTime': [], 'pages': [],
        'warnings': ['list_add_time_semantics_unverified', 'manus_original_time_and_identity_check_required']}
    if not isinstance(source, dict) or source.get('platform') != 'Official Baijing':
        return output
    if source.get('account_name') != '白鲸出海' or source.get('home_url') != BAIJING_HOME:
        output.update(status='unavailable', stopReason='source_configuration_mismatch')
        return output
    output['source'] = {key: source[key] for key in ('account_name', 'platform', 'home_url')}
    if (type(max_pages) is not int or type(max_details) is not int
            or not 1 <= max_pages <= MAX_REQUESTS or not 0 <= max_details <= MAX_REQUESTS
            or max_pages + max_details > MAX_REQUESTS
            or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES
            or type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 15):
        raise ValueError('source seed limits exceed the bounded preflight allowance')
    start, end = timestamp(window['start']), timestamp(window['end'])
    if window.get('timezone') != 'Asia/Shanghai' or end - start != timedelta(days=1):
        raise ValueError('source seed needs a fixed 24-hour Beijing window')
    output['collectionWindow'] = dict(window)
    now_fn = now_fn or (lambda: datetime.now(BJ))
    fetch = transport or _fetch
    started = time.monotonic()

    def request(url, data=None):
        if url != BAIJING_LIST and not _DETAIL_URL.fullmatch(url):
            raise SeedError('url_rejected')
        left = MAX_SECONDS - (time.monotonic() - started)
        if output['requestsAttempted'] >= MAX_REQUESTS or left <= 0:
            raise SeedError('request_or_time_limit')
        output['requestsAttempted'] += 1
        headers = {'User-Agent': 'AI-HOT-source-preflight/1.0', 'Accept-Encoding': 'identity',
                   'Accept': 'application/json' if data else 'text/html'}
        if data:
            headers.update({'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest', 'Referer': BAIJING_HOME})
        req = Request(url, data=data, headers=headers, method='POST' if data else 'GET')
        try:
            status, final_url, body = fetch(req, min(timeout_seconds, left), max_bytes)
        except SeedError:
            raise
        except HTTPError as exc:
            raise SeedError('redirect_rejected' if 300 <= exc.code < 400 else f'http_{exc.code}') from None
        except (URLError, OSError, TimeoutError):
            raise SeedError('network_unavailable') from None
        if final_url != url:
            raise SeedError('redirect_rejected')
        if status != 200:
            raise SeedError(f'http_{status}' if type(status) is int else 'http_error')
        if not isinstance(body, bytes) or len(body) > max_bytes:
            raise SeedError('response_size_limit')
        try:
            text = body.decode('utf-8')
        except UnicodeError:
            raise SeedError('response_encoding_unverified') from None
        if _challenge(text):
            raise SeedError('security_verification')
        observed = now_fn()
        if not isinstance(observed, datetime) or observed.tzinfo is None:
            raise SeedError('observation_time_unverified')
        return text, observed.astimezone(BJ), hashlib.sha256(body).hexdigest()

    def failed(exc):
        code = str(exc)
        output['stopReason'] = code
        output['status'] = ('blocked' if code in ('security_verification', 'http_401', 'http_403', 'http_429')
                            else 'partial' if output['observations'] else 'unavailable')

    seen, stop = set(), False
    for page in range(1, max_pages + 1):
        try:
            text, observed, digest = request(BAIJING_LIST, f'type=0&pn={page}'.encode('ascii'))
            rows, count, rejected = _parse_list(text, page, observed, start, end)
            output['pages'].append({'page': page, 'rowCount': count, 'rejectedRows': rejected,
                                   'observedAt': observed.isoformat(), 'sha256': digest})
            fresh = []
            for row in rows:
                if row['url'] not in seen:
                    seen.add(row['url'])
                    fresh.append(row)
            output['observations'].extend(fresh)
            if rejected:
                output['warnings'].append('list_rows_rejected')
            if not count or not fresh:
                output['stopReason'] = 'empty_list' if not count else 'no_new_list_rows'
                break
            # Never stop paging merely because a relative display looks old.
        except SeedError as exc:
            failed(exc)
            stop = True
            break
    if not stop:
        output.update(status='available', stopReason=output.get('stopReason', 'page_limit'))
        rows = output['observations']
        possible = [row for row in rows if row['windowHint'] not in ('before_window', 'after_window')]
        # Probe a likely window item, a coarse/uncertain time and the oldest
        # observed list row. This is sampling, never proof of complete ordering.
        probes = possible[:1] + [row for row in possible if row['windowHint'] in ('unknown', 'overlaps_boundary')][:1] + rows[-1:]
        probes += possible + rows
        checked = set()
        for row in probes:
            if len(checked) >= max_details:
                break
            if row['url'] in checked:
                continue
            checked.add(row['url'])
            try:
                text, observed, digest = request(row['url'])
                row['detailObservedAt'] = observed.isoformat()
                row['detailSha256'] = digest
                row['headerTime'] = parse_baijing_detail(text, row['title'])
                at = timestamp(row['headerTime']['displayedAt'])
                row['windowHint'] = _relation(at, at + timedelta(minutes=1), start, end)
                row['timeBasis'] = 'article_header_timeago'
            except SeedError as exc:
                row['detailStatus'] = str(exc)
                if str(exc) in ('detail_title_unverified', 'detail_time_unverified'):
                    continue
                failed(exc)
                break

    for row in output['observations']:
        if row.get('headerTime') and row['windowHint'] in ('before_window', 'after_window'):
            output['excludedByHeaderTime'].append(row)
        elif row['windowHint'] not in ('before_window', 'after_window'):
            output['candidates'].append(row)
    reported = [row for row in output['observations'] if row.get('headerTime')]
    earliest = min(reported, key=lambda row: timestamp(row['headerTime']['displayedAt']), default=None)
    times = [timestamp(row['headerTime']['displayedAt']) for row in reported]
    estimates = [row for row in output['observations'] if row.get('listTimeEstimate')]
    earliest_estimate = min(estimates, key=lambda row: timestamp(row['listTimeEstimate']['earliest']), default=None)
    output['boundary'] = {'coverageVerified': False, 'ordering': 'unverified',
        'observedHeaderOrder': ('insufficient_sample' if len(times) < 2 else 'out_of_order'
            if any(newer < older for newer, older in zip(times, times[1:])) else 'nonincreasing_sample'),
        'earliestHeaderTime': earliest['headerTime']['displayedAt'] if earliest else None,
        'earliestHeaderUrl': earliest['url'] if earliest else None,
        'earliestListEstimate': earliest_estimate['listTimeEstimate'] if earliest_estimate else None,
        'headerBeforeStartSeen': any(row['windowHint'] == 'before_window' for row in reported),
        'reason': 'bounded_pages_and_unverified_list_time_or_pinning'}
    return output
