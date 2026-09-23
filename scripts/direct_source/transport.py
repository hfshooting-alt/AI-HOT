"""Bounded anonymous requests with immutable private response receipts."""
import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from manus_source.window import BJ
from manus_source.source_urls import tencent_article_id

HOSTS = frozenset(('news.qq.com', 'view.inews.qq.com', 'i.news.qq.com',
                  'www.163.com', 'www.baijing.cn', 'elsewhere.news',
                  'jigou.jiqizhixin.com'))


def allowed(url):
    p = urllib.parse.urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password
            or p.port not in (None, 443)):
        raise ValueError('Unapproved direct collection URL')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, directory, max_requests=240, timeout=20, max_bytes=3_000_000):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_requests, self.timeout, self.max_bytes = max_requests, timeout, max_bytes
        self.count = 0
        self.blocked = False
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, url, *, method='GET', data=None):
        allowed(url)
        if method not in ('GET', 'POST'):
            raise ValueError('Unsupported method')
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode()
        elif isinstance(data, str):
            data = data.encode()
        original = url
        for hop in range(3):
            with self.lock:
                if self.blocked:
                    raise ValueError('Source access temporarily blocked; no further requests')
                if self.count >= self.max_requests:
                    raise ValueError('Anonymous request limit reached')
                self.count += 1
                sequence = self.count
            observed = datetime.now(BJ).isoformat(timespec='seconds')
            stem = self.directory / f'{sequence:04d}'
            receipt = {'url': url, 'originalUrl': original, 'method': method,
                       'observedAt': observed, 'redirectHop': hop}
            if data:
                receipt['requestBodySha256'] = hashlib.sha256(data).hexdigest()
            headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/json',
                       'Accept-Encoding': 'identity'}
            if method == 'POST':
                headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
                if url == 'https://www.baijing.cn/index/ajax/get_article/':
                    headers.update({'X-Requested-With': 'XMLHttpRequest',
                                    'Referer': 'https://www.baijing.cn/article/'})
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                try:
                    response = self.opener.open(req, timeout=self.timeout)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    receipt['httpStatus'] = response.code
                    raw = response.read(self.max_bytes + 1)
                    if len(raw) > self.max_bytes:
                        raise ValueError('Response size limit exceeded')
                    digest = hashlib.sha256(raw).hexdigest()
                    stem.with_suffix('.body').write_bytes(raw)
                    receipt.update(sha256=digest, bytes=len(raw))
                    if response.code in (301, 302, 303, 307, 308):
                        target = urllib.parse.urljoin(url, response.headers.get('Location', ''))
                        allowed(target)
                        before, after = tencent_article_id(original), tencent_article_id(target)
                        if not before or before != after:
                            raise ValueError('Unverified article redirect')
                        receipt['redirectTo'] = target
                        url = target
                        continue
                    if response.code != 200:
                        if response.code in (401, 403, 429):
                            self.blocked = True
                        raise ValueError(f'HTTP {response.code}')
                    charset = response.headers.get_content_charset() or 'utf-8'
                    text = raw.decode(charset, errors='replace')
                    return {'url': url, 'text': text, 'observedAt': observed,
                            'sha256': digest, 'receipt': str(stem.with_suffix('.json'))}
            except Exception as exc:
                receipt['errorType'] = type(exc).__name__
                raise
            finally:
                stem.with_suffix('.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        raise ValueError('Redirect limit exceeded')
