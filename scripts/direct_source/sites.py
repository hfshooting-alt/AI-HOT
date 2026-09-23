"""Observed anonymous site adapters; no model, browser, guessed IDs or network client.

The injected fetcher owns raw HTTP evidence and network policy. Only the original
publication marker on the configured carrier page is authoritative here; no
adapter claims to establish the earliest publication across the whole web.
"""
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit, parse_qs

from manus_source.source_seeds import parse_baijing_detail, _challenge
from manus_source.window import BJ, timestamp

MAX_PAGES = 10
MAX_DETAILS = 200
BAIJING_HOME = 'https://www.baijing.cn/article/'
BAIJING_LIST = 'https://www.baijing.cn/index/ajax/get_article/'
ELSEWHERE_HOME = 'https://elsewhere.news/zh/articles'
# Observed same-source author page, not a replacement outlet or guessed API.
ELSEWHERE_AUTHOR = 'https://elsewhere.news/zh/elsewhere'
JIQ_HOME = 'https://jigou.jiqizhixin.com/industry'
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_BLOCK = {'p', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'li', 'tr', 'blockquote', 'br'}
_SKIP = {'script', 'style', 'noscript', 'template', 'nav', 'button', 'iframe'}


class SiteError(ValueError):
    """Fixed safe reason code, never an HTTP body or exception message."""


class Node:
    def __init__(self, tag='', attrs=(), seq=0):
        self.tag, self.attrs, self.seq, self.children = tag, dict(attrs), seq, []

    def has(self, name):
        return name in self.attrs.get('class', '').split()

    def find(self, predicate):
        result = []
        for child in self.children:
            if isinstance(child, Node):
                if predicate(child):
                    result.append(child)
                result.extend(child.find(predicate))
        return result

    def text(self, clean=False):
        if self.tag in _SKIP or self.tag.startswith('sidebar-'):
            return ''
        value = ''.join(c.text(clean) if isinstance(c, Node) else c for c in self.children)
        if clean and self.tag in ('p', 'div'):
            compact = _norm(value)
            if (compact.startswith('【本篇文章属于白鲸出海原创，如需转载：')
                    or compact.startswith('友情提醒：白鲸出海目前仅有微信群与QQ群，')
                    or (compact.startswith('文章信息来自于') and '不代表白鲸出海官方立场' in compact)):
                return ''
        return ('\n' + value + '\n') if self.tag in _BLOCK else value


class Document(HTMLParser):
    """Small stdlib-only DOM: extraction cannot crash a shared native parser."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root, self.seq = Node(), 0
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.seq += 1
        node = Node(tag, attrs, self.seq)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def find(self, predicate):
        return self.root.find(predicate)


def _norm(text):
    return ' '.join(text.split())


def _body(node):
    text = '\n'.join(_norm(line) for line in node.text(clean=True).splitlines() if _norm(line)) if node else ''
    return text if len(text) >= 100 else ''


def _one(nodes):
    if len(nodes) != 1:
        raise SiteError('ambiguous_or_missing_detail_field')
    return nodes[0]


def _safe(url, host, pattern, query=False):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.netloc == host and not p.username
                and not p.fragment and (query or not p.query)
                and '%' not in p.path and re.fullmatch(pattern, p.path) is not None)
    except ValueError:
        return False


def _read(fetch, url, **kwargs):
    response = fetch(url, **kwargs)
    if not isinstance(response, dict) or not isinstance(response.get('text'), str):
        raise SiteError('response_schema_unverified')
    if response.get('url') != url:
        raise SiteError('redirect_unverified')
    timestamp(response['observedAt'])
    if _challenge(response['text']):
        raise SiteError('security_verification')
    return response


def _evidence(response, field, raw, precision):
    normalized = (datetime.strptime(raw, '%Y-%m-%d %H:%M').replace(tzinfo=BJ).isoformat()
                  if field == 'time.timeago' else timestamp(raw).isoformat())
    return {'field': field, 'originalText': raw, 'observedAt': response['observedAt'], 'normalizedAt': normalized,
            'precision': precision, 'kind': 'absolute', 'url': response['url'],
            'htmlSha256': response['sha256'], 'originalPlatformPublication': True,
            'earliestGlobalPublicationVerified': False}


def _item(title, url, published, body, evidence, **validation):
    return {'title': title, 'url': url, 'publishedAt': published, 'publishedPrecision': 'datetime',
            'timeEvidence': evidence, 'content_text': body,
            'validation': {'titleMatched': True, 'sourceMatched': True,
                           'publicationTimeVerified': True, 'bodyStatus': 'complete' if body else 'awaiting_body',
                           'contentSha256': sha256(body.encode()).hexdigest() if body else None,
                           **validation}}


def _baijing_detail(response, row):
    doc = Document(response['text'])
    head = _one(doc.find(lambda n: n.has('mod-head') and n.find(lambda c: c.tag == 'h1')))
    title = _norm(_one(head.find(lambda n: n.tag == 'h1')).text())
    ident = row['url'].rsplit('/', 1)[-1]
    ids = doc.find(lambda n: n.has('thisId'))
    if len(ids) != 1 or ids[0].attrs.get('id') != ident:
        raise SiteError('article_identity_unverified')
    containers = doc.find(lambda n: n.attrs.get('id') == 'message')
    container = containers[0] if len(containers) == 1 else None
    raw_body = container.text() if container else ''
    original_titles = [line.strip()[len('原标题：'):].strip() for line in raw_body.splitlines()
                       if line.strip().startswith('原标题：')]
    title_basis = 'header_h1'
    if title != row['title']:
        if row['title'] not in map(_norm, original_titles):
            raise SiteError('detail_title_unverified')
        title_basis = 'same_page_exact_original_title'
    header = parse_baijing_detail(response['text'], title)
    body = _body(container)
    credited = re.search(r'文章信息来自于(.+?)，不代表白鲸出海官方立场', _norm(raw_body))
    own = '本篇文章属于白鲸出海原创' in raw_body
    return _item(row['title'], row['url'], header['displayedAt'], body,
                 _evidence(response, 'time.timeago', header['displayedTimeText'], 'minute'),
                 titleBasis=title_basis, sourceIdentityBasis='configured_host_and_article_id',
                 siteClaimsOriginal=own, attributedOriginalSource='白鲸出海' if own else credited[1] if credited else None,
                 bodyContainer='#message', removedSiteBoilerplate=True)


def _baijing(result, window, fetch):
    home = _read(fetch, BAIJING_HOME)
    html = home['text']
    if not (re.search(r"\$\.post\([\"']/index/ajax/get_article/[\"']", html)
            and "'/article/'+item.id" in html and 'this.articleForm.pn ++' in html
            and re.search(r'articleForm\s*:\s*\{\s*type\s*:\s*(?:0|[\"\'][\"\']\s*\|\|\s*0)\s*,\s*pn\s*:\s*1', html)):
        raise SiteError('list_route_not_exposed')
    seen, exhausted = set(), False
    for page in range(1, MAX_PAGES + 1):
        response = _read(fetch, BAIJING_LIST, method='POST', data=f'type=0&pn={page}'.encode())
        payload = json.loads(response['text'])
        rows = payload.get('data', {}).get('article_list')
        if payload.get('success') is not True or type(payload.get('code')) is not int or payload['code'] != 0 or not isinstance(rows, list) or len(rows) > 100:
            raise SiteError('list_schema_unverified')
        result['coverage']['pages'] += 1
        result['listRows'] += len(rows)
        if not rows:
            exhausted = True
            break
        fresh = 0
        for row in rows:
            ident = str(row.get('id', '')) if isinstance(row, dict) else ''
            title = _norm(row.get('title', '')) if isinstance(row, dict) and isinstance(row.get('title'), str) else ''
            if not re.fullmatch(r'[1-9][0-9]{0,11}', ident) or not title:
                result['coverage']['rejectedRows'] += 1
                continue
            url = BAIJING_HOME + ident
            if url in seen:
                continue
            seen.add(url)
            fresh += 1
            if result['coverage']['details'] >= MAX_DETAILS:
                result['reason'] = 'detail_limit'
                return
            _detail(result, window, fetch, {'url': url, 'title': title, 'listEvidence': {
                'url': BAIJING_LIST, 'sha256': response['sha256'], 'page': page,
                'listTimeText': row.get('add_time')}}, _baijing_detail)
        if not fresh:
            result['reason'] = 'repeated_list_page'
            return
    _finish(result, exhausted, 'page_limit')


def _meta(doc, name):
    values = {n.attrs.get('content', '').strip() for n in doc.find(
        lambda n: n.tag == 'meta' and n.attrs.get('property') == name)}
    if len(values) != 1 or not next(iter(values)):
        raise SiteError('detail_metadata_unverified')
    return next(iter(values))


def _elsewhere_detail(response, row):
    doc = Document(response['text'])
    title = _norm(_one(doc.find(lambda n: n.tag == 'h1')).text())
    if title != row['title']:
        raise SiteError('detail_title_unverified')
    if _meta(doc, 'article:author') != 'elsewhere别处发生':
        raise SiteError('article_author_mismatch')
    authors = doc.find(lambda n: n.tag == 'a' and urljoin(response['url'], n.attrs.get('href', '')) == ELSEWHERE_AUTHOR)
    if not any(_norm(n.text()) == 'elsewhere别处发生' for n in authors):
        raise SiteError('article_author_unbound')
    published = _meta(doc, 'article:published_time')
    at = timestamp(published)
    # dateModified is deliberately not a fallback.
    bodies = doc.find(lambda n: n.has('prose-article'))
    body = _body(bodies[0] if len(bodies) == 1 else None)
    return _item(title, row['url'], at.isoformat(), body,
                 _evidence(response, 'article:published_time', published, 'second'),
                 sourceIdentityBasis='article_author_meta_and_same_author_link', bodyContainer='.prose-article')


def _cards(doc, base):
    rows, other, rejected = [], 0, 0
    podcast = [n.seq for n in doc.find(lambda n: n.tag == 'h2' and _norm(n.text()) == '播客')]
    for card in doc.find(lambda n: n.tag == 'article' and (not podcast or n.seq < min(podcast))):
        links = card.find(lambda n: n.tag == 'a' and _safe(urljoin(base, n.attrs.get('href', '')), 'elsewhere.news', r'/zh/[^/]+/[^/]+'))
        if not links:
            rejected += 1
            continue
        url = urljoin(base, links[0].attrs['href'])
        names = card.find(lambda n: n.has('content-meta-name'))
        if not _safe(url, 'elsewhere.news', r'/zh/elsewhere/[A-Za-z0-9_-]+') or not names or any(_norm(n.text()) != 'elsewhere别处发生' for n in names):
            other += 1
            continue
        headings = card.find(lambda n: n.tag == 'h3')
        if len(headings) != 1:
            rejected += 1
            continue
        rows.append({'url': url, 'title': _norm(headings[0].text())})
    return rows, other, rejected


def _elsewhere(result, window, fetch):
    mixed = _read(fetch, ELSEWHERE_HOME)
    _, other, _ = _cards(Document(mixed['text']), ELSEWHERE_HOME)
    result['coverage']['excludedOtherAuthors'] = other
    # This author route was observed and verified separately in the pilot; the
    # mixed portal currently need not show this author on its first page.
    next_url, seen_pages, seen_articles = ELSEWHERE_AUTHOR, set(), set()
    for page in range(1, MAX_PAGES + 1):
        if next_url in seen_pages:
            result['reason'] = 'repeated_list_page'
            return
        seen_pages.add(next_url)
        response = _read(fetch, next_url)
        doc = Document(response['text'])
        if _norm(_one(doc.find(lambda n: n.tag == 'h1')).text()) != 'elsewhere别处发生':
            raise SiteError('author_page_identity_unverified')
        if not doc.find(lambda n: n.tag == 'h2' and _norm(n.text()) == '文章'):
            raise SiteError('author_article_section_unverified')
        rows, other, rejected = _cards(doc, next_url)
        result['coverage']['excludedOtherAuthors'] += other
        result['coverage']['rejectedRows'] += rejected + other
        result['coverage']['pages'] += 1
        result['listRows'] += len(rows)
        for row in rows:
            if row['url'] in seen_articles:
                continue
            seen_articles.add(row['url'])
            if result['coverage']['details'] >= MAX_DETAILS:
                result['reason'] = 'detail_limit'
                return
            row['listEvidence'] = {'url': next_url, 'sha256': response['sha256'], 'page': page}
            _detail(result, window, fetch, row, _elsewhere_detail)
        next_links = []
        for link in doc.find(lambda n: n.tag == 'a' and 'href' in n.attrs):
            url = urljoin(next_url, link.attrs['href'])
            if not _safe(url, 'elsewhere.news', r'/zh/elsewhere', query=True):
                continue
            query = parse_qs(urlsplit(url).query)
            if query == {'ap': [str(page + 1)]}:
                next_links.append(url)
        if not next_links:
            # No visible next link proves only the exposed author-page chain.
            _finish(result, True, None)
            result['coverage']['scope'] = 'exposed_author_article_pages'
            return
        next_url = next_links[0]
    _finish(result, False, 'page_limit')


def _detail(result, window, fetch, row, parse):
    result['coverage']['details'] += 1
    try:
        response = _read(fetch, row['url'])
        item = parse(response, row)
        item['validation']['listEvidence'] = row.get('listEvidence')
        if response.get('receipt'):
            item['validation']['detailReceipt'] = response['receipt']
        at = timestamp(item['publishedAt'])
        if not timestamp(window['start']) <= at < timestamp(window['end']):
            result['coverage']['outsideWindow'] += 1
            return
        if not item['content_text']:
            result['coverage']['awaitingBody'] += 1
        result['items'].append(item)
    except Exception as error:
        code = str(error) if isinstance(error, SiteError) else type(error).__name__
        result['coverage']['detailFailures'].append({'url': row['url'], 'reason': code})
        if (code == 'security_verification' or getattr(error, 'code', None) in (401, 403, 429)
                or str(error) in ('HTTP 401', 'HTTP 403', 'HTTP 429', 'Anonymous request limit reached')):
            raise SiteError('access_restricted') from None


def _finish(result, exhausted, reason):
    coverage = result['coverage']
    coverage['listExhausted'] = exhausted
    coverage['complete'] = bool(exhausted and not coverage['detailFailures'] and not coverage['rejectedRows'])
    result['status'] = 'complete' if coverage['complete'] and not coverage['awaitingBody'] else 'partial'
    result['reason'] = ('awaiting_body' if coverage['complete'] and coverage['awaitingBody'] else
                        'list_exhausted' if coverage['complete'] else reason or 'details_unverified')


def collect(source, window, fetch, out_dir):
    """Return only source/title/original carrier-publication verified items.

    Bounds: ten exposed list pages, 200 detail requests, no retry. Raw responses
    belong to the injected transport; adapter decisions are private in out_dir.
    Missing bodies keep eligible metadata with an explicit awaiting_body status.
    """
    result = {'source': dict(source), 'items': [], 'status': 'partial', 'reason': None, 'listRows': 0,
              'coverage': {'complete': False, 'scope': 'exposed_site_pages', 'pages': 0, 'details': 0,
                           'listExhausted': False, 'outsideWindow': 0, 'awaitingBody': 0,
                           'rejectedRows': 0, 'detailFailures': []}}
    try:
        if timestamp(window['start']) >= timestamp(window['end']):
            raise SiteError('invalid_window')
        identity = (source.get('account_name'), source.get('platform'), source.get('home_url'))
        if identity == ('白鲸出海', 'Official Baijing', BAIJING_HOME):
            _baijing(result, window, fetch)
        elif identity == ('elsewhere别处发生', 'Official Elsewhere', ELSEWHERE_HOME):
            _elsewhere(result, window, fetch)
        elif identity == ('机器之心', 'Official Jiqizhixin', JIQ_HOME):
            response = _read(fetch, JIQ_HOME)
            doc = Document(response['text'])
            titles = doc.find(lambda n: n.tag == 'title')
            service = any('数据服务' in n.text() for n in titles)
            result.update(status='failed', reason='data_service_wall' if service else 'article_list_contract_unverified')
            result['coverage']['pages'] = 1
        else:
            raise SiteError('source_not_supported')
    except Exception as error:
        result['status'] = 'partial' if result['items'] else 'failed'
        result['reason'] = str(error) if isinstance(error, SiteError) else type(error).__name__
    try:
        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        # Trace decisions contain no article body; raw evidence remains private.
        audit = {key: value for key, value in result.items() if key != 'items'}
        audit['accepted'] = [{key: value for key, value in item.items() if key != 'content_text'} for item in result['items']]
        (path / 'site-decisions.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as error:
        result['coverage']['diagnosticError'] = type(error).__name__
    return result
