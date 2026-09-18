"""Bounded public-page rendering for configured dynamic article sites."""
from html import escape
from threading import BoundedSemaphore
from urllib.parse import urlparse

_slots = BoundedSemaphore(2)


def supported(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'jigou.jiqizhixin.com'
            and parsed.path.startswith('/articles/') and not parsed.username)


def fetch_article(url, timeout_seconds=30):
    """Read one anonymous rendered page, with no login, retries or paid services."""
    if not supported(url):
        raise ValueError('No renderer configured for this article source')
    from playwright.sync_api import sync_playwright
    with _slots, sync_playwright() as runtime:
        browser = runtime.chromium.launch(timeout=15000)
        try:
            page = browser.new_page()
            timeout = min(max(timeout_seconds, 1), 30) * 1000
            page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            # Observed article body selector; do not mistake navigation/login
            # widgets or a data-service landing page for the actual article.
            body = page.locator('.detail__info-body')
            body.wait_for(state='visible', timeout=timeout)
            title = page.title()
            text = body.inner_text(timeout=timeout)
            html = '<html><head><title>' + escape(title) + '</title></head><body><article>'
            html += ''.join('<p>' + escape(line) + '</p>' for line in text.splitlines() if line.strip())
            html += '</article></body></html>'
            return page.url, html.encode('utf-8')
        finally:
            browser.close()
