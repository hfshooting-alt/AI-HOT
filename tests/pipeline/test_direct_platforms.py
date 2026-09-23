"""Offline platform coverage and detail admission; no external services."""
from copy import deepcopy
from html import escape
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from direct_source import platforms as p

SOURCE = {'account_name': '智东西', 'platform': 'Tencent News',
          'home_url': 'https://news.qq.com/omn/author/8QMc2XZf7IAfsD3Z'}
NETEASE = {'account_name': '硅星人', 'platform': 'NetEase',
           'home_url': 'https://www.163.com/dy/media/T1506509934914.html'}
WINDOW = {'start': '2026-09-22T13:08:06+08:00', 'end': '2026-09-23T13:08:06+08:00',
          'timezone': 'Asia/Shanghai'}
OBSERVED = '2026-09-23T13:30:00+08:00'
BODY = '这是经过公开文章详情核验的独立正文，包含足够的信息供后续单独分类。' * 6


def txrow(ident='20260923A0000100', when='2026-09-23 12:30:03', title='文章一', **extra):
    return {'id': ident, 'title': title, 'url': f'https://view.inews.qq.com/a/{ident}',
            'time': when, 'chlname': '智东西', 'card': {'suid': '8QMc2XZf7IAfsD3Z', 'chlname': '智东西'}, **extra}


def page(rows, cursor='', more=False):
    return {'ret': 0, 'newslist': rows, 'offsetInfo': cursor, 'hasNext': int(more)}


def response(text, url):
    text = json.dumps(text, ensure_ascii=False) if isinstance(text, dict) else text
    return {'url': url, 'text': text, 'observedAt': OBSERVED,
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'receipt': 'private/response.json'}


def detail(row, source=SOURCE, *, title=None, pub=None, header=None, home=None, author=None, body=BODY):
    when = pub or row['time']
    head = header or when
    author = author or source['account_name']
    home = home or source['home_url']
    platform = source['platform']
    attr = 'id="article-author"' if platform == 'Tencent News' else 'class="post_info"'
    container = 'rich_media_content' if platform == 'Tencent News' else 'post_body'
    return (f'<html><head><title>{escape(title or row["title"])}</title>'
            f'<meta property="article:published_time" content="{escape(when)}"></head><body>'
            f'<h1'+(' id="article-title"' if platform == 'Tencent News' else '')+f'>{escape(title or row["title"])}</h1><div {attr}>'
            f'<a href="{escape(home)}">{escape(author)}</a><span>{escape(head)}</span></div>'
            + (f'<div class="{container}"><p>{escape(body)}</p></div>' if body is not None else '')
            + '<div class="recommend">推荐的无关内容</div></body></html>')


def ntrow(ident='L7GP22360511N33R', when='2026-09-23 11:24', title='当Qwen开始训练Qwen'):
    return {'title': title, 'time': when, 'url': f'https://www.163.com/dy/article/{ident}.html?spss=dy_author'}


def ntlist(rows, source=NETEASE):
    return (f'<html><head><title>{source["account_name"]}</title><link rel="canonical" href="{source["home_url"]}"></head><body>'
            + ''.join(f'<li class="js-item item"><h4><a class="title" href="{escape(r["url"])}">{escape(r["title"])}</a></h4>'
                      f'<span class="time">{r["time"]}</span></li>' for r in rows) + '</body></html>')


class Fake:
    def __init__(self, pages, details=None):
        self.pages, self.details, self.calls = pages, details or {}, []

    def __call__(self, url, *, method='GET', data=None):
        assert method == 'GET' and data is None
        self.calls.append(url)
        if url.startswith(p.TENCENT_LIST):
            cursor = parse_qs(urlsplit(url).query, keep_blank_values=True)['offset_info'][0]
            result = self.pages[cursor]
        elif url in self.pages:
            result = self.pages[url]
        else:
            result = self.details[url]
        if isinstance(result, Exception):
            raise result
        return result if isinstance(result, dict) and 'sha256' in result else response(result, url)


class DirectPlatforms(unittest.TestCase):
    def collect(self, fake, source=SOURCE):
        with tempfile.TemporaryDirectory() as tmp:
            return p.collect(source, WINDOW, fake, Path(tmp))

    def test_cursor_is_opaque_next_offset_not_decoded_or_guessed(self):
        one, two = txrow(), txrow('20260923A0000200', '2026-09-23 11:00:00', '文章二')
        cursor = '%7B%22lastPubTime%22%3A%222026-09-23+12%3A30%3A03%22%7D'
        fake = Fake({'': page([one], cursor, True), cursor: page([two])},
                    {r['url']: detail(r) for r in (one, two)})
        result = self.collect(fake)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['coverage']['listExhausted'])
        self.assertIn('offset_info=%257B', fake.calls[1])
        self.assertEqual(parse_qs(urlsplit(fake.calls[1]).query)['offset_info'], [cursor])
        self.assertEqual(result['items'][0]['timeEvidence'], {
            'kind': 'absolute', 'originalText': one['time'], 'observedAt': OBSERVED,
            'field': 'detail.meta.article:published_time + article header',
            'normalizedAt': '2026-09-23T12:30:03+08:00'})
        self.assertEqual(result['items'][0]['collector'], 'direct_site')

    def test_observed_lower_boundary_stops_but_never_claims_complete_coverage(self):
        one, old = txrow(), txrow('20260921A0000200', '2026-09-21 12:00:00', '旧文')
        fake = Fake({'': page([one, old], 'next', True)}, {one['url']: detail(one)})
        result = self.collect(fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(result['coverage']['boundaryReached'])
        self.assertFalse(result['coverage']['coverageComplete'])
        self.assertEqual(result['status'], 'partial')

    def test_out_of_order_old_pinned_row_does_not_stop_pagination(self):
        old, one = txrow('20260921A0000200', '2026-09-21 12:00:00'), txrow()
        fake = Fake({'': page([old, one], 'next', True), 'next': page([])}, {one['url']: detail(one)})
        result = self.collect(fake)
        self.assertEqual(result['coverage']['listPages'], 2)
        self.assertEqual(result['coverage']['ordering'], 'unverified')

    def test_page_failure_preserves_preceding_valid_detail_without_retry(self):
        row = txrow()
        fake = Fake({'': page([row], 'next', True), 'next': TimeoutError('private error')}, {row['url']: detail(row)})
        result = self.collect(fake)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(fake.calls), 3)
        self.assertNotIn('private error', json.dumps(result))

    def test_repeated_cursor_and_ten_page_hard_limit(self):
        row = txrow()
        fake = Fake({'': page([row], 'x', True), 'x': page([row], 'x', True)}, {row['url']: detail(row)})
        result = self.collect(fake)
        self.assertEqual(result['reason'], 'pagination_cursor_missing_or_repeated')
        self.assertEqual(result['coverage']['detailRequests'], 1)
        pages, details = {}, {}
        for i in range(10):
            r = txrow(f'20260923A{i:05d}00')
            pages['' if i == 0 else str(i)] = page([r], str(i+1), True)
            details[r['url']] = detail(r)
        fake = Fake(pages, details)
        result = self.collect(fake)
        self.assertEqual(result['coverage']['listPages'], 10)
        self.assertIn('list_pages', result['coverage']['limitsReached'])

    def test_detail_cap_no_hidden_retry_or_request(self):
        one, two = txrow(), txrow('20260923A0000200')
        fake = Fake({'': page([one, two])}, {one['url']: detail(one)})
        with patch.object(p, 'MAX_DETAILS', 1):
            result = self.collect(fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn('detail_requests', result['coverage']['limitsReached'])
        self.assertEqual(result['status'], 'partial')

    def test_wrong_source_or_unsafe_url_never_requested(self):
        for source in ({**SOURCE, 'home_url': SOURCE['home_url'].replace('news.qq.com', 'news.qq.com.evil')},
                       {**NETEASE, 'home_url': 'https://www.163.com/dy/media/T000.html'}):
            fake = Fake({})
            self.assertEqual(self.collect(fake, source)['status'], 'failed')
            self.assertFalse(fake.calls)
        bad = txrow(url='https://127.0.0.1/private')
        missing = txrow(); missing.pop('id'); missing.pop('url')
        fake = Fake({'': page([bad, missing])})
        result = self.collect(fake)
        self.assertFalse(result['items'])
        self.assertEqual(len(fake.calls), 1)

    def test_strict_detail_identity_title_publication_gates(self):
        row = txrow()
        cases = [detail(row, title='另一个标题'), detail(row, home=SOURCE['home_url']+'wrong'),
                 detail(row, author='另一家媒体'), detail(row, pub='2026-09-22 12:30:03'),
                 detail(row, header='2026-09-23 12:30:02'),
                 detail(row).replace('article:published_time', 'article:modified_time')]
        for body in cases:
            with self.subTest(body=body[:100]):
                fake = Fake({'': page([row])}, {row['url']: body})
                result = self.collect(fake)
                self.assertFalse(result['items'])
                self.assertEqual(result['coverage']['unresolvedCandidates'], 1)

    def test_alias_redirect_same_id_only_and_url_preserved(self):
        row = txrow()
        url = 'https://news.qq.com/rain/a/' + row['id'] + '?id=' + row['id']
        fake = Fake({'': page([row])}, {row['url']: response(detail(row), url)})
        self.assertEqual(self.collect(fake)['items'][0]['url'], row['url'])
        for target in (url.replace(row['id'], '20260923A0009900'), url+'&ID=DIFFERENT', url.replace('news.qq.com','news.qq.com:443')):
            fake = Fake({'': page([row])}, {row['url']: response(detail(row), target)})
            self.assertFalse(self.collect(fake)['items'])

    def test_single_bad_article_does_not_drop_other_article(self):
        one, two = txrow(), txrow('20260923A0000200', title='文章二')
        fake = Fake({'': page([one, two])}, {one['url']: TimeoutError(), two['url']: detail(two)})
        result = self.collect(fake)
        self.assertEqual([x['title'] for x in result['items']], ['文章二'])
        self.assertEqual(result['status'], 'partial')

    def test_metadata_only_when_body_missing_or_extractor_failure(self):
        row = txrow()
        fake = Fake({'': page([row])}, {row['url']: detail(row, body=None)})
        item = self.collect(fake)['items'][0]
        self.assertEqual(item['content_text'], '')
        self.assertTrue(item['validation']['metadataOnly'])
        self.assertTrue(item['validation']['sourceMatched'])
        with patch.object(p, '_body', side_effect=RuntimeError('internal')):
            item = self.collect(Fake({'': page([row])}, {row['url']: detail(row)}))['items'][0]
        self.assertEqual(item['content_text'], '')

    def test_challenge_detail_is_not_metadata_only_news(self):
        row = txrow()
        body = detail(row).replace('<title>文章一</title>', '<title>安全验证</title>')
        self.assertFalse(self.collect(Fake({'': page([row])}, {row['url']: body}))['items'])

    def test_tencent_section_h1_and_empty_h1_do_not_replace_unique_page_title(self):
        row = txrow()
        body = detail(row).replace('<p>', '<h1>正文内部小标题</h1><h1>\u00a0</h1><p>', 1)
        result = self.collect(Fake({'': page([row])}, {row['url']: body}))
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['validation']['titleSelector'], '//h1[@id="article-title"]')
        self.assertIn('正文内部小标题', result['items'][0]['content_text'])
        # A matching section title cannot rescue a mismatched, missing, or ambiguous page title.
        for changed in (body.replace('id="article-title">文章一', 'id="article-title">另一篇'),
                        body.replace('id="article-title"', 'id="other"'),
                        body.replace('<body>', '<body><h1 id="article-title">文章一</h1>')):
            self.assertFalse(self.collect(Fake({'': page([row])}, {row['url']: changed}))['items'])

    def test_tencent_plain_paragraph_body_requires_exact_observed_article_container(self):
        row = txrow()
        original = detail(row, body=None)
        wrapped = f'<div id="article-content"><div class="article-top-content">不要收这里</div><div class="comps-contentify-wrap comps-contentify-pc-wrap"><div class="qnt-p">{BODY}</div></div></div>'
        body = original.replace('</body>', wrapped + '</body>')
        item = self.collect(Fake({'': page([row])}, {row['url']: body}))['items'][0]
        self.assertEqual(item['content_text'], BODY)
        self.assertEqual(item['validation']['bodySelector'], '#article-content > .comps-contentify-wrap > .qnt-p')
        for bad in (body.replace('id="article-content"','id="recommend"'),
                    body.replace('class="qnt-p"','class="recommend"')):
            item = self.collect(Fake({'': page([row])}, {row['url']: bad}))['items'][0]
            self.assertEqual(item['content_text'], '')

    def test_window_end_and_precise_yesterday_outside_are_not_reincluded(self):
        start = txrow('20260922A0000100', '2026-09-22 13:08:06')
        end = txrow('20260923A0000200', '2026-09-23 13:08:06')
        old = txrow('20260922A0000300', '2026-09-22 12:31:07')
        fake = Fake({'': page([end, start, old])}, {start['url']: detail(start)})
        result = self.collect(fake)
        self.assertEqual([r['publishedAt'] for r in result['items']], [WINDOW['start']])
        self.assertEqual(result['coverage']['detailRequests'], 1)

    def test_duplicate_mobile_desktop_id_one_detail(self):
        one = txrow(); alias = {**one, 'url': 'https://news.qq.com/rain/a/'+one['id']+'?app=news'}
        fake = Fake({'': page([one, alias])}, {one['url']: detail(one)})
        result = self.collect(fake)
        self.assertEqual(result['coverage']['detailRequests'], 1)
        self.assertEqual(len(result['items']), 1)

    def test_netease_ssr_query_url_minute_time_and_header_identity(self):
        row = ntrow()
        fake = Fake({NETEASE['home_url']: ntlist([row])},
                    {row['url']: detail(row, NETEASE, pub='2026-09-23T11:24:11+08:00', header='2026-09-23 11:24:11')})
        result = self.collect(fake, NETEASE)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['publishedAt'], '2026-09-23T11:24:11+08:00')
        self.assertIn('?spss=dy_author', result['items'][0]['url'])
        self.assertFalse(result['coverage']['coverageComplete'])
        self.assertEqual(result['coverage']['listPages'], 1)
        self.assertNotIn('推荐的无关内容', result['items'][0]['content_text'])

    def test_netease_empty_shell_not_zero_news_and_canonical_binding(self):
        for body in (ntlist([]), ntlist([ntrow()]).replace(NETEASE['home_url'], 'https://www.163.com/dy/media/T000.html')):
            fake = Fake({NETEASE['home_url']: body})
            result = self.collect(fake, NETEASE)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['coverage']['listRowsVerified'], 0)

    def test_netease_one_hundred_old_rows_keep_explicit_first_page_boundary(self):
        rows = [ntrow(f'L7G{i:05d}0511N33R', '2026-09-20 11:00') for i in range(100)]
        result = self.collect(Fake({NETEASE['home_url']: ntlist(rows)}), NETEASE)
        self.assertEqual(result['listRows'], 100)
        self.assertTrue(result['coverage']['boundaryReached'])
        self.assertEqual(result['coverage']['detailRequests'], 0)
        self.assertEqual(result['status'], 'partial')

    def test_body_footer_and_scripts_excluded_only_inside_known_container(self):
        row = txrow()
        body = detail(row).replace('</p></div>', '</p><div class="post_statement">平台声明</div><script>secretScript</script></div>')
        result = self.collect(Fake({'': page([row])}, {row['url']: body}))
        self.assertEqual(result['items'][0]['content_text'], BODY)

    def test_input_objects_unchanged_and_evidence_write_error_does_not_lose_item(self):
        row = txrow(); source, window = deepcopy(SOURCE), deepcopy(WINDOW)
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'write_text', side_effect=RuntimeError('diagnostic')):
            result = p.collect(source, window, Fake({'': page([row])}, {row['url']: detail(row)}), Path(tmp))
        self.assertEqual(len(result['items']), 1)
        self.assertEqual((source, window), (SOURCE, WINDOW))
        self.assertEqual(result['diagnostics'][-1]['reason'], 'evidence_write_RuntimeError')


if __name__ == '__main__':
    unittest.main()
