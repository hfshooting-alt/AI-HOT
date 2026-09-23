"""Offline observed-site fixtures: identity/time boundaries and bounded discovery."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from direct_source import sites


WINDOW = {'start': '2026-09-22T13:08:06+08:00', 'end': '2026-09-23T13:08:06+08:00'}
WHITE = {'account_name': '白鲸出海', 'platform': 'Official Baijing', 'home_url': sites.BAIJING_HOME}
ELSE = {'account_name': 'elsewhere别处发生', 'platform': 'Official Elsewhere', 'home_url': sites.ELSEWHERE_HOME}
JIQ = {'account_name': '机器之心', 'platform': 'Official Jiqizhixin', 'home_url': sites.JIQ_HOME}
BODY = '这是一段有来源的报道，产品通过实际使用获得增长，不能据此推断用户数等于收入。' * 8
HOME = '''<a :href="'/article/'+item.id"></a><script>
articleForm:{type:"" || 0,pn:1}; $.post("/index/ajax/get_article/",this.articleForm,go);
this.articleForm.pn ++;</script>'''


def listing(*rows):
    return json.dumps({'success': True, 'code': 0, 'data': {'article_list': list(rows)}})


def white(ident, title='原文标题', when='2026-09-23 11:27', body=BODY):
    return (f'<b class="thisId" id="{ident}"></b><div class="mod-head"><h1>{title}</h1>'
            f'<time class="timeago">{when}</time></div><div id="message"><p>{body}</p>'
            '<p>【本篇文章属于白鲸出海原创，如需转载：需联系授权方可，未经授权严转载!】</p>'
            '<p>友情提醒：白鲸出海目前仅有微信群与QQ群，并无在Telegram等其他社交软件创建群。</p>'
            '<sidebar-ad-ma2>广告公司ABC</sidebar-ad-ma2></div><div>本文相关公司：推荐公司XYZ</div>'
            '<div class="mod-head">评论区</div>')


def card(slug='story', title='原文标题', author='elsewhere别处发生', prefix='elsewhere'):
    return (f'<article><a href="/zh/{prefix}/{slug}"><span>{title}</span></a>'
            f'<h3>{title}</h3><span class="content-meta-name">{author}</span>'
            '<time>2026年9月23日</time></article>')


def author_page(cards='', links=''):
    return '<h1>elsewhere别处发生</h1><h2>文章</h2>' + cards + links


def elsewhere(title='原文标题', author='elsewhere别处发生', published='2026-09-23T03:24:11Z', body=BODY):
    return (f'<meta property="article:published_time" content="{published}">'
            f'<meta property="article:author" content="{author}"><h1>{title}</h1>'
            f'<a href="/zh/elsewhere">{author}</a><div class="prose-article"><p>{body}</p></div>'
            '<nav>推荐模块不能入正文</nav>')


class FakeFetch:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, url, *, method='GET', data=None):
        self.calls.append((url, method, data))
        value = self.replies[(url, data)] if (url, data) in self.replies else self.replies[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict):
            return value
        return {'url': url, 'text': value, 'observedAt': '2026-09-23T13:10:00+08:00',
                'sha256': hashlib.sha256(value.encode()).hexdigest()}


class DirectSites(unittest.TestCase):
    def run_site(self, source, replies):
        fetch = FakeFetch(replies)
        with tempfile.TemporaryDirectory() as out:
            result = sites.collect(source, WINDOW, fetch, out)
            audit = json.loads((Path(out) / 'site-decisions.json').read_text(encoding='utf-8'))
        self.assertNotIn('content_text', json.dumps(audit))
        return result, fetch

    def white_replies(self, rows, details):
        return {sites.BAIJING_HOME: HOME,
                (sites.BAIJING_LIST, b'type=0&pn=1'): listing(*rows),
                (sites.BAIJING_LIST, b'type=0&pn=2'): listing(), **details}

    def test_baijing_public_route_pagination_body_scope_and_time(self):
        replies = self.white_replies([{'id': 56800, 'title': '原文标题', 'add_time': '昨天', 'is_original': 1}],
                                     {sites.BAIJING_HOME+'56800': white('56800')})
        result, fetch = self.run_site(WHITE, replies)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['items']), 1)
        item = result['items'][0]
        self.assertEqual(item['content_text'], BODY)
        self.assertEqual(item['timeEvidence']['normalizedAt'], item['publishedAt'])
        self.assertEqual(item['timeEvidence']['originalText'], '2026-09-23 11:27')
        self.assertFalse(item['timeEvidence']['earliestGlobalPublicationVerified'])
        self.assertEqual(fetch.calls[-1][2], b'type=0&pn=2')

    def test_baijing_is_original_flag_does_not_override_repost_attribution(self):
        html = white('123').replace('【本篇文章属于白鲸出海原创，如需转载：需联系授权方可，未经授权严转载!】',
                                  '文章信息来自于原作者，不代表白鲸出海官方立场，内容仅供网友参考学习。')
        result, _ = self.run_site(WHITE, self.white_replies([{'id': 123, 'title': '原文标题', 'is_original': 1}],
                                                          {sites.BAIJING_HOME+'123': html}))
        item = result['items'][0]
        self.assertFalse(item['validation']['siteClaimsOriginal'])
        self.assertEqual(item['validation']['attributedOriginalSource'], '原作者')
        self.assertNotIn('原作者', item['content_text'])

    def test_baijing_only_exact_same_page_original_title_resolves_list_title_difference(self):
        html = white('123', title='承载页简标题', body='原标题：列表完整标题</p><p>' + BODY)
        result, _ = self.run_site(WHITE, self.white_replies([{'id': 123, 'title': '列表完整标题'}],
                                                          {sites.BAIJING_HOME+'123': html}))
        self.assertEqual(result['items'][0]['validation']['titleBasis'], 'same_page_exact_original_title')
        self.assertEqual(result['items'][0]['title'], '列表完整标题')

    def test_bad_detail_does_not_drop_good_article_or_claim_complete(self):
        rows = [{'id': 1, 'title': '原文标题'}, {'id': 2, 'title': '原文标题'}]
        result, _ = self.run_site(WHITE, self.white_replies(rows, {
            sites.BAIJING_HOME+'1': white('1', title='别的标题'), sites.BAIJING_HOME+'2': white('2')}))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([x['url'] for x in result['items']], [sites.BAIJING_HOME+'2'])
        self.assertEqual(len(result['coverage']['detailFailures']), 1)

    def test_precise_out_of_window_time_never_gets_yesterday_exception(self):
        rows = [{'id': 1, 'title': '原文标题', 'add_time': '昨天'}, {'id': 2, 'title': '原文标题'}]
        result, _ = self.run_site(WHITE, self.white_replies(rows, {
            sites.BAIJING_HOME+'1': white('1', when='2026-09-22 10:00'),
            sites.BAIJING_HOME+'2': white('2', when='2026-09-23 14:00')}))
        self.assertEqual(result['items'], [])
        self.assertEqual(result['coverage']['outsideWindow'], 2)

    def test_missing_body_preserves_verified_metadata(self):
        result, _ = self.run_site(WHITE, self.white_replies([{'id': 1, 'title': '原文标题'}],
                                                          {sites.BAIJING_HOME+'1': white('1', body='')}))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['items'][0]['content_text'], '')
        self.assertEqual(result['items'][0]['validation']['bodyStatus'], 'awaiting_body')

    def test_unexposed_route_or_wrong_source_never_posts(self):
        result, fetch = self.run_site(WHITE, {sites.BAIJING_HOME: '<h1>新网站</h1>'})
        self.assertEqual(result['reason'], 'list_route_not_exposed')
        self.assertEqual(len(fetch.calls), 1)
        result, fetch = self.run_site({**WHITE, 'home_url': 'https://evil.test/'}, {})
        self.assertEqual(result['reason'], 'source_not_supported')
        self.assertEqual(fetch.calls, [])

    def test_bounded_pages_and_details_and_no_guessed_urls(self):
        replies = {sites.BAIJING_HOME: HOME}
        for page in range(1, 4):
            replies[(sites.BAIJING_LIST, f'type=0&pn={page}'.encode())] = listing({'id': page, 'title': '原文标题'})
            replies[sites.BAIJING_HOME+str(page)] = white(str(page))
        with patch.object(sites, 'MAX_PAGES', 2):
            result, fetch = self.run_site(WHITE, replies)
        self.assertEqual(result['reason'], 'page_limit')
        self.assertEqual(result['coverage']['pages'], 2)
        with patch.object(sites, 'MAX_DETAILS', 1):
            result, fetch = self.run_site(WHITE, replies)
        self.assertEqual(result['reason'], 'detail_limit')
        self.assertEqual(result['coverage']['details'], 1)

    def test_repeated_page_is_not_end_of_feed_and_unsafe_id_is_not_fetched(self):
        rows = [{'id': 1, 'title': '原文标题'}, {'id': '../secrets', 'title': '危险'}]
        replies = self.white_replies(rows, {sites.BAIJING_HOME+'1': white('1')})
        replies[(sites.BAIJING_LIST, b'type=0&pn=2')] = listing(*rows)
        result, fetch = self.run_site(WHITE, replies)
        self.assertEqual(result['reason'], 'repeated_list_page')
        self.assertFalse(result['coverage']['complete'])
        self.assertFalse(any('secrets' in x[0] for x in fetch.calls))

    def test_access_restriction_stops_source_without_more_details(self):
        rows = [{'id': 1, 'title': '原文标题'}, {'id': 2, 'title': '原文标题'}]
        result, fetch = self.run_site(WHITE, self.white_replies(rows, {sites.BAIJING_HOME+'1': ValueError('HTTP 429')}))
        self.assertEqual(result['reason'], 'access_restricted')
        self.assertFalse(any(x[0].endswith('/2') for x in fetch.calls))

    def test_elsewhere_follows_only_observed_author_pagination_not_other_authors(self):
        second = sites.ELSEWHERE_AUTHOR+'?ap=2'
        replies = {sites.ELSEWHERE_HOME: card(prefix='other', author='其他作者'),
                   sites.ELSEWHERE_AUTHOR: author_page(card(), '<a href="/zh/elsewhere?ap=2">下一页</a>'),
                   second: author_page(), sites.ELSEWHERE_AUTHOR+'/story': elsewhere()}
        result, fetch = self.run_site(ELSE, replies)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['coverage']['excludedOtherAuthors'], 1)
        self.assertEqual(result['items'][0]['content_text'], BODY)
        self.assertEqual(result['items'][0]['publishedAt'], '2026-09-23T11:24:11+08:00')
        self.assertIn((second, 'GET', None), fetch.calls)
        self.assertFalse(any('/other/' in x[0] for x in fetch.calls))

    def test_elsewhere_podcast_section_is_not_article_and_update_time_is_not_publication(self):
        page = author_page(card()) + '<h2>播客</h2>' + card('podcast')
        detail = elsewhere().replace('article:published_time', 'article:modified_time')
        result, fetch = self.run_site(ELSE, {sites.ELSEWHERE_HOME: '', sites.ELSEWHERE_AUTHOR: page,
                                          sites.ELSEWHERE_AUTHOR+'/story': detail})
        self.assertEqual(result['items'], [])
        self.assertFalse(result['coverage']['complete'])
        self.assertFalse(any('/podcast' in x[0] for x in fetch.calls))

    def test_elsewhere_detail_author_must_match_exactly(self):
        result, _ = self.run_site(ELSE, {sites.ELSEWHERE_HOME: '', sites.ELSEWHERE_AUTHOR: author_page(card()),
                                       sites.ELSEWHERE_AUTHOR+'/story': elsewhere(author='另一媒体')})
        self.assertEqual(result['items'], [])
        self.assertEqual(result['coverage']['detailFailures'][0]['reason'], 'article_author_mismatch')

    def test_elsewhere_changed_article_link_cannot_be_reported_as_complete_empty(self):
        changed = '<article><a href="https://elsewhere.news.evil.test/zh/elsewhere/fake">坏链接</a></article>'
        result, fetch = self.run_site(ELSE, {sites.ELSEWHERE_HOME: '', sites.ELSEWHERE_AUTHOR: author_page(changed)})
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['coverage']['rejectedRows'], 1)
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(len(fetch.calls), 2)

    def test_jiq_service_wall_is_failed_not_no_news(self):
        result, fetch = self.run_site(JIQ, {sites.JIQ_HOME: '<title>机器之心·数据服务</title><h1>访问数据服务</h1>'})
        self.assertEqual((result['status'], result['reason']), ('failed', 'data_service_wall'))
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(len(fetch.calls), 1)

    def test_diagnostic_write_failure_does_not_drop_verified_items(self):
        fetch = FakeFetch(self.white_replies([{'id': 1, 'title': '原文标题'}], {sites.BAIJING_HOME+'1': white('1')}))
        with tempfile.TemporaryDirectory() as out, patch.object(Path, 'write_text', side_effect=OSError('disk')):
            result = sites.collect(WHITE, WINDOW, fetch, out)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['coverage']['diagnosticError'], 'OSError')


if __name__ == '__main__':
    unittest.main()
