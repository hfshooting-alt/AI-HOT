import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from publication_review import review
from enrich_news import enforce_event_boundary, enrich_one
from company_index.extraction import normalize_company
from company_index.entities import merge_entities
from apply_quality_review import apply
TX=json.loads((ROOT/'config/taxonomy.json').read_text(encoding='utf-8'))

class QualityBoundaries(unittest.TestCase):
    def test_preview_is_not_release_but_actual_independent_product_is(self):
        self.assertEqual(enforce_event_boundary({'category':'release'},'产品发布会预告')['category'],'general')
        self.assertEqual(enforce_event_boundary({'category':'release'},'独立开发者发布新的AI应用')['category'],'release')
        self.assertEqual(enforce_event_boundary({'category':'release'},'前瞻性AI产品现已上线')['category'],'release')

    def test_release_without_verbatim_evidence_is_not_publishable(self):
        with patch('enrich_news.call_llm',return_value=json.dumps({'summary':'产品已经推出。'*20,'category':'release','tags':{},'release_evidence':'输入不存在的引文'})):
            result=enrich_one(TX,{'title':'新品','content_text':'实际只是分享已有模型的使用心得。'*20})
        self.assertNotEqual(result['enrichmentStatus'],'complete')

    def test_original_old_publication_isolated_not_new_discussion(self):
        rules={'records':[{'url':'https://example.com/a','title':'旧文章','originalPublishedDate':'2019-02-14','checkedAt':'2026-09-14','evidence':'2019','reason':'旧闻'}]}
        items=[{'id':'old','title':'旧文章','url':'https://example.com/a'}, {'id':'new','title':'今天的新解读','url':'https://example.com/new'}]
        accepted, isolated=review(items,{'start':'2026-09-13T09:30:00+08:00'},rules)
        self.assertEqual([i['id'] for i in accepted],['new'])
        self.assertEqual(isolated[0]['originalPublishedDate'],'2019-02-14')

    def test_old_url_date_is_only_a_quarantine_hint_not_verified_publication(self):
        items=[{'id':'a','title':'时间未知','url':'https://example.com/2026/08/18/story'}]
        accepted, isolated=review(items,{'start':'2026-09-13T09:30:00+08:00'},{'records':[]})
        self.assertFalse(accepted)
        self.assertEqual(isolated[0]['verificationStatus'],'unverified')
        self.assertNotIn('originalPublishedDate',isolated[0])

    def test_unowned_product_stays_pending_without_changing_news(self):
        article={'id':'a','title':'新AI工具发布','publishedAt':'2026-09-14T08:00:00+08:00','url':'https://example.com/tool','category':'release','dims':{}}
        product=normalize_company({'company_name':'新工具','entity_type':'product','product_names':['新工具']},TX)
        companies=merge_entities([article],{'a':{'companies':[product]}},{'companies':[]},TX)
        snapshot={'all':{'items':[{'id':'a','title':article['title'],'classification':{'cat':'release'}}]}}
        result, snap, _=apply({'schemaVersion':1,'generatedAt':'2026-09-14T10:00:00+08:00','companies':companies,'stats':{},'coverageNote':''},snapshot,{'aliases':{},'pending':{},'classifications':{}},TX)
        self.assertEqual(result['companies'],[])
        self.assertEqual(result['pendingEntities'][0]['company_name'],'新工具')
        self.assertEqual(snap['all']['items'][0]['classification']['cat'],'release')
        self.assertIsNone(normalize_company({'company_name':'个人','entity_type':'person'},TX))
        self.assertEqual(normalize_company({'company_name':'未知主体'},TX)['entity_type'],'product')
