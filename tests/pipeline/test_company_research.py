import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import tag_news
from company_index.identity import apply_reviewed_research
from company_index.research import propose

ROOT = Path(__file__).resolve().parents[2]


class ResearchTest(unittest.TestCase):
    def test_country_fill_preserves_existing_value_and_evidence(self):
        rules = {'checkedAt':'2026-09-10','records':[{'record_name':'X','reviewed':True,'facts':[{'field':'country','value':'美国','url':'https://example.com','title':'Official','quote':'incorporated in Delaware'}]}]}
        row = {'company_name':'X','country':None,'fieldSources':{}}
        filled = apply_reviewed_research([row], rules)
        self.assertEqual(filled[0]['country'], '美国')
        self.assertEqual(filled[0]['fieldSources']['country'][0]['origin'], 'research')
        self.assertEqual(apply_reviewed_research(filled, rules), filled)
        row['country'] = '爱尔兰'
        self.assertEqual(apply_reviewed_research([row], rules), [row])

    def test_failed_request_is_not_repeated(self):
        tx = tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        packet = {'record_name':'X', 'sources':[{'url':'https://example.com','title':'Official','text':'Company X'}]}
        model = Mock(side_effect=TimeoutError('timeout'))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(TimeoutError):
                propose(tx,packet,folder,allow_paid=True,llm_fn=model)
            with self.assertRaisesRegex(ValueError,'不自动重试'):
                propose(tx,packet,folder,allow_paid=True,llm_fn=model)
            self.assertEqual(model.call_count,1)

    def test_unverifiable_quote_rejected(self):
        tx = tag_news.load_taxonomy(str(ROOT / 'config/taxonomy.json'))
        packet = {'record_name':'X','sources':[{'url':'https://example.com','title':'Official','text':'Company X'}]}
        model = Mock(return_value=json.dumps({'entity_type':'company','owner_company':None,'facts':[{'field':'founded','value':'2020','source_index':0,'quote':'not in source'}]}))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'逐字来源'):
                propose(tx,packet,folder,allow_paid=True,llm_fn=model)

    def test_brand_merge_keeps_brand_date_out_of_parent_and_is_idempotent(self):
        base = dict(aliases=[],product_names=[],fieldSources={'company_name':[]},sourceArticles=[],firstSeenAt='2020',lastSeenAt='2026',dims={})
        parent = dict(base,id='company:parent',company_name='Parent',founded='2000',team='Founder')
        brand = dict(base,id='company:brand',company_name='Brand',founded='2020',team='Product leader')
        rules = {'checkedAt':'2026-09-10','records':[{'record_name':'Brand','owner_company':'Parent','reviewed':True,'facts':[{'field':'owner_company','value':'Parent','url':'https://example.com','title':'Official','quote':'Brand by Parent'}]}]}
        result=apply_reviewed_research([parent,brand],rules)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['founded'],'2000')
        self.assertEqual(result[0]['brandProfiles']['Brand']['founded'],'2020')
        self.assertIn('Brand',result[0]['product_names'])
        self.assertEqual(apply_reviewed_research(result,rules),result)
