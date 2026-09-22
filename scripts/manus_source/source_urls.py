"""Recognize narrowly observed article URL aliases without fetching or rewriting.

Matching a Tencent article ID does not establish its publisher, title, content,
publication time, or window eligibility; callers retain those separate gates.
"""
import re
from urllib.parse import parse_qsl, urlsplit


_TENCENT_PATHS = {
    'view.inews.qq.com': re.compile(r'/a/([0-9]{8}[A-Z0-9]{8})'),
    'news.qq.com': re.compile(r'/(?:rain/)?a/([0-9]{8}[A-Z0-9]{8})'),
}


def tencent_article_id(url: str) -> str | None:
    """Return an exact known Tencent article ID, or None for ambiguous URLs.

    Accept only HTTPS, exact known hosts and literal article paths. Explicit
    ports, credentials, escaped paths and conflicting query IDs are rejected.
    Tracking queries/fragments do not change a verified path ID.
    """
    if (not isinstance(url, str) or not url or '\\' in url
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.username is not None or parts.password is not None:
            return None
        # Matching netloc rather than hostname also rejects explicit ports,
        # trailing dots, credentials and suffix lookalikes.
        pattern = _TENCENT_PATHS.get(parts.netloc.lower())
        match = pattern.fullmatch(parts.path) if pattern else None
        if not match:
            return None
        ident = match[1]
        if any(key.lower() == 'id' and value != ident
               for key, value in parse_qsl(parts.query, keep_blank_values=True)):
            return None
        return ident
    except ValueError:
        return None


def same_tencent_article(left: str, right: str) -> bool:
    """Whether both URLs independently identify the same known Tencent article."""
    ident = tencent_article_id(left)
    return ident is not None and ident == tencent_article_id(right)
