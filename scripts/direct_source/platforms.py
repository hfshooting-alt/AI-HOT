"""Anonymous Tencent/NetEase list-to-detail adapters; no model or Manus calls.

Tencent cursor contract is observed in the public channel.js: response
offsetInfo is passed unchanged as the next request's offset_info parameter.
It is an opaque cursor, encoded once by urlencode (even when it contains %).
NetEase uses only the observed SSR account page; no pagination API is guessed.
List dates are hints. Every admitted item has its own detail identity, title,
publication-field and window checks. A chronological sample is not full coverage.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlencode, urlsplit

from lxml import html

from manus_source.source_urls import tencent_article_id
from manus_source.tencent_seeds import _configured, _time_hint, TENCENT_LIST
from manus_source.window import BJ, timestamp

MAX_LIST_PAGES = 10
MAX_DETAILS = 200
MAX_TEXT_BYTES = 3_000_000
MAX_BODY_CHARS = 200_000
_NETEASE = {'ZFinance': 'T1751873060579', 'FounderPark': 'T1705485947430',
            '硅星人': 'T1506509934914'}
_DATE = re.compile(r'20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?')


class EvidenceError(ValueError):
    """Fixed safe diagnostic reason, never a raw server response."""


def _clean(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def _same_title(left, right):
    return bool(left and right) and re.sub(r'\s+', '', left) == re.sub(r'\s+', '', right)


def _account(url, platform):
    if not isinstance(url, str) or '\\' in url or any(ord(c) <= 32 for c in url):
        return None
    p = urlsplit(url)
    if p.scheme != 'https':
        return None
    if platform == 'Tencent News' and p.netloc == 'news.qq.com':
        match = re.fullmatch(r'/omn/author/([A-Za-z0-9%+=]+)', p.path)
        return unquote(match[1]) if match else None
    if platform == 'NetEase' and p.netloc == 'www.163.com':
        match = re.fullmatch(r'/dy/media/(T[0-9]+)\.html', p.path)
        return match[1] if match else None
    return None


def _article_id(url, platform):
    if platform == 'Tencent News':
        return tencent_article_id(url)
    if not isinstance(url, str) or '\\' in url or any(ord(c) <= 32 for c in url):
        return None
    p = urlsplit(url)
    match = re.fullmatch(r'/dy/article/([A-Z0-9]{16})\.html', p.path)
    return match[1] if p.scheme == 'https' and p.netloc == 'www.163.com' and match else None


def _parse_time(value):
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise EvidenceError('publication_time_unverified')
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (at.replace(tzinfo=BJ) if at.tzinfo is None else at.astimezone(BJ))
    except ValueError:
        raise EvidenceError('publication_time_unverified') from None


def _document(text):
    try:
        doc = html.fromstring(text)
    except (ValueError, TypeError):
        raise EvidenceError('html_unreadable') from None
    title = _clean(''.join(doc.xpath('//title/text()'))).lower()
    if (any(s in title for s in ('安全验证', '人机验证', '验证码', 'captcha', 'just a moment'))
            or 'cf-chl-' in text or '/cdn-cgi/challenge-platform/' in text):
        raise EvidenceError('security_verification')
    return doc


def _classes(name):
    return f'contains(concat(" ",normalize-space(@class)," ")," {name} ")'


def _body_nodes(doc, platform):
    selector = 'rich_media_content' if platform == 'Tencent News' else 'post_body'
    nodes = doc.xpath(f'//div[{_classes(selector)}]')
    if not nodes and platform == 'Tencent News':
        # Observed Tencent plain-paragraph template, inside the article body.
        # Never fall back to the entire article-content/page/recommendation text.
        nodes = doc.xpath(f'//div[@id="article-content"]/div[{_classes("comps-contentify-wrap")}]')
        nodes = [node for node in nodes if len(node) and all(
            isinstance(child.tag, str) and child.tag == 'div'
            and 'qnt-p' in (child.get('class') or '').split() for child in node)]
        selector = '#article-content > .comps-contentify-wrap > .qnt-p'
    return nodes, selector


def _body(doc, platform):
    nodes, _ = _body_nodes(doc, platform)
    if len(nodes) != 1:
        return '', 'article_body_container_missing'
    node = deepcopy(nodes[0])
    for child in node.xpath('.//script|.//style|.//nav|.//form|.//iframe|.//button'):
        child.drop_tree()
    for name in ('post_statement', 'post_recommend', 'post_recommends', 'post_top_share'):
        for child in node.xpath(f'.//*[{_classes(name)}]'):
            child.drop_tree()
    blocks = {'p', 'div', 'section', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'tr'}

    def render(element):
        if not isinstance(element.tag, str):
            return ''
        if element.tag == 'br':
            return '\n'
        result = element.text or ''
        for child in element:
            result += render(child) + (child.tail or '')
        return '\n' + result + '\n' if element.tag in blocks else result

    text = '\n'.join(line.strip() for line in render(node).splitlines() if line.strip())
    if len(text) < 100:
        return '', 'article_body_too_short'
    if len(text) > MAX_BODY_CHARS:
        return '', 'article_body_size_limit'
    return text, 'complete'


def _response(fetch, url, evidence):
    response = fetch(url, method='GET')
    if (not isinstance(response, dict) or not isinstance(response.get('text'), str)
            or not isinstance(response.get('url'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', response.get('sha256', ''))):
        raise EvidenceError('transport_response_invalid')
    timestamp(response.get('observedAt'))
    if len(response['text'].encode('utf-8')) > MAX_TEXT_BYTES:
        raise EvidenceError('response_size_limit')
    evidence.append({key: response[key] for key in ('url', 'observedAt', 'sha256', 'receipt') if key in response})
    return response


def _tencent_rows(source, known, payload, observed, start, end):
    if (not isinstance(payload, dict) or type(payload.get('ret')) is not int or payload['ret'] != 0
            or not isinstance(payload.get('newslist'), list) or len(payload['newslist']) > 20
            or type(payload.get('hasNext')) not in (bool, int) or payload['hasNext'] not in (0, 1)):
        raise EvidenceError('tencent_list_schema_unverified')
    rows, issues = [], []
    for index, raw in enumerate(payload['newslist']):
        if not isinstance(raw, dict):
            issues.append({'index': index, 'reason': 'list_row_invalid'})
            continue
        card = raw.get('card') if isinstance(raw.get('card'), dict) else {}
        link = raw.get('link_info') if isinstance(raw.get('link_info'), dict) else {}
        url = raw.get('url') or link.get('url')
        if (not _article_id(url, 'Tencent News') or _article_id(url, 'Tencent News') != raw.get('id') or not _clean(raw.get('title'))
                or card.get('suid') != known[0]
                or raw.get('chlname') not in known[1] or card.get('chlname') not in known[1]):
            issues.append({'index': index, 'reason': 'list_identity_unverified'})
            continue
        label, relation, basis, displayed, conflict = _time_hint(raw, observed, start, end)
        rows.append({'title': raw['title'], 'url': url, 'listTimeText': label,
                     'listDisplayedAt': displayed, 'windowHint': relation, 'timeBasis': basis,
                     'listTimeConflict': conflict,
                     'listPrecision': 'minute' if displayed and re.search(r'\d{2}:\d{2}(?::|$)', label)
                     and not re.search(r'\d{2}:\d{2}:\d{2}', label) and not label.isdigit() else 'second'})
    return rows, issues


def _netease_rows(source, response, start, end):
    if response['url'] != source['home_url']:
        raise EvidenceError('list_redirect_unverified')
    doc = _document(response['text'])
    if (_clean(''.join(doc.xpath('//title/text()'))) != source['account_name']
            or doc.xpath('//link[@rel="canonical"]/@href') != [source['home_url']]):
        raise EvidenceError('list_identity_unverified')
    nodes = doc.xpath(f'//li[{_classes("js-item")}]')
    if not nodes or len(nodes) > 100:
        raise EvidenceError('netease_list_structure_unverified')
    rows, issues = [], []
    for index, node in enumerate(nodes):
        links = node.xpath(f'.//h4/a[{_classes("title")}]')
        labels = node.xpath(f'.//span[{_classes("time")}]')
        if (len(links) != 1 or len(labels) != 1
                or not _article_id(links[0].get('href'), 'NetEase') or not _clean(links[0].text_content())):
            issues.append({'index': index, 'reason': 'list_row_invalid'})
            continue
        label = _clean(labels[0].text_content())
        try:
            at = _parse_time(label)
            precision = 'second' if re.search(r'\d{2}:\d{2}:\d{2}', label) else 'minute'
            upper = at + (timedelta(minutes=1) if precision == 'minute' else timedelta(0))
            relation = ('before_window' if upper < start else 'after_window' if at >= end else
                        'within_window' if start <= at and upper <= end else 'overlaps_boundary')
        except EvidenceError:
            at, relation, precision = None, 'unknown', 'unknown'
        rows.append({'title': links[0].text_content().strip(), 'url': links[0].get('href'),
                     'listTimeText': label, 'listDisplayedAt': at.isoformat() if at else None,
                     'listPrecision': precision, 'windowHint': relation, 'listTimeConflict': False})
    return rows, issues, len(nodes)


def _detail(source, known, row, response, window):
    platform = source['platform']
    ident = _article_id(row['url'], platform)
    if not ident or _article_id(response['url'], platform) != ident:
        raise EvidenceError('article_redirect_unverified')
    doc = _document(response['text'])
    # Tencent articles may legitimately use h1 for body section headings.
    # The unique observed page-title ID, not the first/any h1, is authoritative.
    title_selector = '//h1[@id="article-title"]' if platform == 'Tencent News' else '//h1'
    headings = doc.xpath(title_selector)
    if len(headings) != 1 or not _same_title(headings[0].text_content(), row['title']):
        raise EvidenceError('detail_title_mismatch')
    headers = doc.xpath('//*[@id="article-author"]') if platform == 'Tencent News' else doc.xpath(f'//div[{_classes("post_info")}]')
    expected = _account(source['home_url'], platform)
    matched = [node for node in headers if any(_account(url, platform) == expected for url in node.xpath('.//a/@href'))]
    if not matched:
        raise EvidenceError('detail_source_identity_mismatch')
    aliases = known[1] if platform == 'Tencent News' else (source['account_name'],)
    author_links = [a for node in matched for a in node.xpath('.//a[@href]') if _account(a.get('href'), platform) == expected]
    if not any(_clean(a.text_content()) in aliases for a in author_links):
        raise EvidenceError('detail_source_name_mismatch')
    # Generic meta author=网易/腾讯网 is not the media identity; header binding above is required.
    values = doc.xpath('//meta[@property="article:published_time"]/@content')
    if len(values) != 1:
        raise EvidenceError('publication_time_unverified')
    at = _parse_time(values[0])
    header_times = [(m[0], _parse_time(m[0])) for node in matched for m in _DATE.finditer(node.text_content())]
    if not header_times or not any((at == t if re.search(r'\d{2}:\d{2}:\d{2}', label)
                                   else 0 <= (at - t).total_seconds() < 60) for label, t in header_times):
        raise EvidenceError('publication_header_conflict')
    if row.get('listTimeConflict'):
        raise EvidenceError('list_time_conflict')
    if row.get('listDisplayedAt'):
        listed = timestamp(row['listDisplayedAt'])
        delta = (at - listed).total_seconds()
        if (row.get('listPrecision') == 'minute' and not 0 <= delta < 60
                or row.get('listPrecision') != 'minute' and delta != 0):
            raise EvidenceError('list_detail_publication_conflict')
    if not timestamp(window['start']) <= at < timestamp(window['end']):
        return None
    try:
        text, body_status = _body(doc, platform)
    except Exception as exc:
        text, body_status = '', 'body_extraction_' + type(exc).__name__
    publication = at.isoformat()
    return {'title': row['title'], 'url': row['url'], 'publishedAt': publication,
            'publishedPrecision': 'datetime',
            'timeEvidence': {'kind': 'absolute', 'originalText': values[0], 'observedAt': response['observedAt'],
                             'field': 'detail.meta.article:published_time + article header', 'normalizedAt': publication},
            'content_text': text, 'sourcePlatform': platform, 'collector': 'direct_site',
            'validation': {'passed': True, 'titleMatched': True, 'titleSelector': title_selector,
                           'sourceMatched': True,
                           'publicationTimeVerified': True, 'earliestCrossPlatformOriginalTimeVerified': False,
                           'listTimeText': row['listTimeText'], 'listDisplayedAt': row.get('listDisplayedAt'),
                           'sourceHomeUrl': source['home_url'], 'detailUrl': response['url'],
                           'detailSha256': response['sha256'], 'detailReceipt': response.get('receipt'),
                           'bodyStatus': body_status, 'bodySelector': _body_nodes(doc, platform)[1],
                           'metadataOnly': not bool(text),
                           'bodySha256': hashlib.sha256(text.encode('utf-8')).hexdigest() if text else None}}


def collect(source: dict, window: dict, fetch, out_dir: Path) -> dict:
    """Collect one configured platform, sequentially; outer scheduler owns concurrency.

    fetch is the caller's bounded anonymous transport; no retries, credentials,
    environment loading, alternative API guesses, or independent network access.
    out_dir receives only adapter evidence; raw responses belong to the transport.
    """
    source, window = deepcopy(source), deepcopy(window)
    result = {'source': source, 'items': [], 'status': 'failed', 'reason': '', 'listRows': 0,
              'coverage': {'coverageComplete': False, 'boundaryReached': False, 'listExhausted': False,
                           'listPages': 0, 'detailRequests': 0, 'listRowsVerified': 0, 'unresolvedCandidates': 0,
                           'maxListPages': MAX_LIST_PAGES, 'maxDetails': MAX_DETAILS,
                           'ordering': 'unverified', 'limitsReached': [], 'metadataOnlyItems': 0}}
    coverage = result['coverage']
    evidence, issues, candidates = [], [], []
    stop_reason = ''
    try:
        start, end = timestamp(window['start']), timestamp(window['end'])
        if window.get('timezone') != 'Asia/Shanghai' or end - start != timedelta(days=1):
            raise EvidenceError('window_invalid')
        platform = source.get('platform')
        known = _configured(source) if platform == 'Tencent News' else None
        if platform == 'Tencent News' and not known:
            raise EvidenceError('source_configuration_mismatch')
        if platform == 'NetEase':
            ident = _NETEASE.get(source.get('account_name'))
            if not ident or source.get('home_url') != f'https://www.163.com/dy/media/{ident}.html':
                raise EvidenceError('source_configuration_mismatch')
        elif platform != 'Tencent News':
            raise EvidenceError('unsupported_platform')

        cursors, seen = set(), {}
        cursor, previous, order_ok, all_times = '', None, True, True
        for page in range(1, MAX_LIST_PAGES + 1):
            if platform == 'Tencent News':
                url = TENCENT_LIST + '?' + urlencode({'offset_info': cursor, 'guestSuid': known[0],
                                                     'tabId': 'om_article', 'caller': 1, 'from_scene': 103})
            else:
                url = source['home_url']
            response = _response(fetch, url, evidence)
            if response['url'] != url:
                raise EvidenceError('list_redirect_unverified')
            coverage['listPages'] += 1
            if platform == 'Tencent News':
                try:
                    payload = json.loads(response['text'])
                except ValueError:
                    raise EvidenceError('tencent_list_schema_unverified') from None
                rows, rejected = _tencent_rows(source, known, payload, timestamp(response['observedAt']), start, end)
                result['listRows'] += len(payload['newslist'])
            else:
                rows, rejected, total = _netease_rows(source, response, start, end)
                result['listRows'] += total
            issues.extend({'stage': 'list', 'page': page, **x} for x in rejected)
            coverage['listRowsVerified'] += len(rows)
            newly_seen = 0
            for row in rows:
                ident = _article_id(row['url'], platform)
                if ident in seen:
                    if not _same_title(row['title'], seen[ident]['title']) or row.get('listDisplayedAt') != seen[ident].get('listDisplayedAt'):
                        issues.append({'stage': 'list', 'reason': 'duplicate_metadata_conflict', 'url': row['url']})
                    continue
                seen[ident] = row
                newly_seen += 1
                row['listEvidence'] = {k: response[k] for k in ('url', 'observedAt', 'sha256', 'receipt') if k in response}
                at = timestamp(row['listDisplayedAt']) if row.get('listDisplayedAt') else None
                if at is None or row.get('listTimeConflict'):
                    all_times = False
                else:
                    if previous is not None and at > previous:
                        order_ok = False
                    previous = at
                if row['windowHint'] not in ('before_window', 'after_window'):
                    candidates.append(row)
            coverage['ordering'] = 'observed_nonincreasing' if order_ok and all_times else 'unverified'
            if rows and not rejected and all_times and order_ok and any(r['windowHint'] == 'before_window' for r in rows):
                coverage['boundaryReached'] = True
            if platform == 'NetEase':
                stop_reason = 'netease_ssr_boundary_reached' if coverage['boundaryReached'] else 'netease_ssr_page_limit'
                coverage['limitsReached'].append('netease_single_ssr_page')
                break
            if not payload['hasNext']:
                coverage['listExhausted'] = True
                stop_reason = 'list_exhausted'
                break
            if coverage['boundaryReached']:
                stop_reason = 'observed_time_boundary_reached'
                break
            next_cursor = payload.get('offsetInfo')
            if not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 8192 or next_cursor in cursors or next_cursor == cursor:
                issues.append({'stage': 'list', 'reason': 'pagination_cursor_missing_or_repeated'})
                stop_reason = 'pagination_cursor_missing_or_repeated'
                break
            if not newly_seen:
                issues.append({'stage': 'list', 'reason': 'pagination_no_progress'})
                stop_reason = 'pagination_no_progress'
                break
            cursors.add(next_cursor)
            cursor = next_cursor
        else:
            stop_reason = 'list_page_limit'
            coverage['limitsReached'].append('list_pages')
    except Exception as exc:
        code = str(exc) if isinstance(exc, EvidenceError) else type(exc).__name__
        issues.append({'stage': 'list', 'reason': code})
        stop_reason = code

    # Earlier good pages survive a later page failure. Each article is isolated.
    for row in candidates[:MAX_DETAILS]:
        coverage['detailRequests'] += 1
        try:
            response = _response(fetch, row['url'], evidence)
            item = _detail(source, known, row, response, window)
            if item is not None:
                item['validation']['listEvidence'] = row['listEvidence']
                result['items'].append(item)
        except Exception as exc:
            code = str(exc) if isinstance(exc, EvidenceError) else type(exc).__name__
            issues.append({'stage': 'detail', 'url': row['url'], 'reason': code})
    if len(candidates) > MAX_DETAILS:
        coverage['limitsReached'].append('detail_requests')
        issues.append({'stage': 'detail', 'reason': 'detail_limit', 'notAttempted': len(candidates) - MAX_DETAILS})
    coverage['candidateHints'] = len(candidates)
    coverage['unresolvedCandidates'] = sum(1 for x in issues if x['stage'] == 'detail')
    coverage['metadataOnlyItems'] = sum(not item['content_text'] for item in result['items'])
    coverage['coverageComplete'] = coverage['listExhausted'] and not issues and not coverage['limitsReached']
    coverage['scope'] = 'Configured platform feed only; list ordering samples do not prove all original-media publication coverage.'
    result['status'] = ('complete' if coverage['coverageComplete'] else 'partial' if result['items'] or coverage['listRowsVerified'] else 'failed')
    result['reason'] = stop_reason or 'partial_evidence'
    result['diagnostics'] = issues
    try:
        directory = Path(out_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'platform-evidence.json'
        path.write_text(json.dumps({'source': source, 'window': window, 'coverage': coverage,
                                   'requests': evidence, 'issues': issues}, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        result['diagnostics'].append({'stage': 'evidence', 'reason': 'evidence_write_' + type(exc).__name__})
    return result
