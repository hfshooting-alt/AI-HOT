"""Observed Tencent hydration payload recovery with strict provenance binding."""
from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest

from direct_source import platforms as p
from .test_direct_platforms import SOURCE, WINDOW, BODY, txrow, page, detail, Fake


class EmbeddedBodyTests(unittest.TestCase):
    def setUp(self):
        self.row = txrow()
        self.data = {'url': self.row['url'], 'article_id': self.row['id'],
                     'title': self.row['title'], 'media': SOURCE['account_name'],
                     'pubtime': self.row['time'], 'card': {'suid': '8QMc2XZf7IAfsD3Z', 'chlname': '智东西'},
                     'article_is_pay': False, 'isOversize': False,
                     'originContent': {'text': '<div class="rich_media_content"><p>'+BODY+'</p></div>'}}

    def run_page(self, data=None, shell=None, double=False):
        payload = self.data if data is None else data
        script = '<script>window.DATA = '+json.dumps(payload,ensure_ascii=False)+';</script>'
        body = '<html><head><title>新闻</title></head><body></body></html>' if shell is None else shell
        body = body.replace('</body>', script*(2 if double else 1)+'</body>')
        with tempfile.TemporaryDirectory() as folder:
            return p.collect(SOURCE, WINDOW, Fake({'':page([self.row])}, {self.row['url']:body}), Path(folder))

    def test_shell_recovers_body_without_javascript_or_additional_requests(self):
        result = self.run_page()
        self.assertEqual(result['items'][0]['content_text'], BODY)
        self.assertEqual(result['items'][0]['timeEvidence']['field'], 'window.DATA.pubtime')
        self.assertEqual(result['coverage']['detailRequests'], 1)

    def test_visible_metadata_without_body_can_use_embedded_full_text(self):
        result = self.run_page(shell=detail(self.row,body=None))
        self.assertEqual(result['items'][0]['content_text'], BODY)

    def test_embedded_flat_paragraphs_have_no_dependency_on_page_layout(self):
        data=deepcopy(self.data);data['originContent']['text']='<!--marker--><P>'+BODY+'</P><P>结尾</P>'
        item=self.run_page(data)['items'][0]
        self.assertEqual(item['content_text'],BODY+'\n结尾')

    def test_different_article_source_time_or_truncated_payload_cannot_rescue_shell(self):
        cases = [('article_id','20260923A9999900'), ('url','https://evil.test/a'),
                 ('media','其他媒体'), ('pubtime','2026-09-22 12:30:03'),
                 ('title','另一个标题'), ('title',12), ('article_is_pay',True), ('isOversize',True),
                 ('card',{'suid':'wrong','chlname':'智东西'}), ('originContent',{'text':BODY})]
        for key,value in cases:
            with self.subTest(key=key,value=str(value)[:30]):
                data=deepcopy(self.data);data[key]=value
                result=self.run_page(data)
                self.assertFalse(any(i['content_text'] for i in result['items']))

    def test_conflicting_visible_identity_never_overridden_by_embedded_data(self):
        for shell in (detail(self.row,title='另一篇'),detail(self.row,author='其他媒体'),
                      detail(self.row,pub='2026-09-23 11:00:00'),detail(self.row,header='2026-09-23 11:00:00')):
            self.assertFalse(self.run_page(shell=shell)['items'])

    def test_ambiguous_payload_or_challenge_never_rescued(self):
        self.assertFalse(self.run_page(double=True)['items'])
        self.assertFalse(self.run_page(shell='<html><head><title>安全验证</title></head><body></body></html>')['items'])

    def test_bad_fallback_keeps_original_verified_metadata_only(self):
        data=deepcopy(self.data);data['card']['suid']='wrong'
        result=self.run_page(data,shell=detail(self.row,body=None))
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['items'][0]['content_text'],'')
