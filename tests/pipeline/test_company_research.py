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
    def test_provisional_only_fills_blanks_and_does_not_merge_candidates(self):
        fact={'field':'country','value':'英国','verificationStatus':'provisional','reason':'历史总部口径，现主体待核实','url':'https://example.com','title':'About','quote':'London'}
        candidate={'name':'Parent','url':'https://example.com','quote':'Parent','reason':'维护方，法人归属未定','checkedAt':'2026-09-15'}
        rules={'checkedAt':'2026-09-15','records':[{'record_name':'X','reviewed':True,'facts':[fact],'candidateOwners':[candidate]}]}
        row={'company_name':'X','country':None,'fieldSources':{}}
        result=apply_reviewed_research([row],rules)
        self.assertEqual(result[0]['country'],'英国')
        self.assertEqual(result[0]['company_name'],'X')
        self.assertEqual(result[0]['candidateOwners'],[candidate])
        self.assertEqual(apply_reviewed_research(result,rules),result)
        row['country']='美国';fact['replace']=True
        self.assertEqual(apply_reviewed_research([row],rules)[0]['country'],'美国')
        fact['field']='owner_company'
        with self.assertRaises(ValueError):apply_reviewed_research([row],rules)

    def test_reviewed_replacement_keeps_old_evidence_and_registration_scope(self):
        old={'value':'2022','articleId':'news','origin':'article'}
        row={'company_name':'X','founded':'2022','fieldSources':{'founded':[old]}}
        fact={'field':'founded','value':'2021-06-30','replace':True,'dateBasis':'registration','legalEntity':'X Group Inc.','url':'https://example.com/filing','title':'Filing','quote':'incorporated on June 30, 2021'}
        rules={'checkedAt':'2026-09-15','records':[{'record_name':'X','reviewed':True,'facts':[fact]}]}
        result=apply_reviewed_research([row],rules)
        self.assertEqual(result[0]['founded'],'2021-06-30')
        self.assertEqual(result[0]['fieldSources']['founded'][0],old)
        self.assertEqual(result[0]['fieldSources']['founded'][1]['legalEntity'],'X Group Inc.')
        self.assertEqual(apply_reviewed_research(result,rules),result)

    def test_division_merge_preserves_news_without_inventing_product(self):
        base=dict(aliases=[],product_names=[],fieldSources={},sourceArticles=[],firstSeenAt='2020',lastSeenAt='2026')
        company=dict(base,id='company:parent',company_name='Parent')
        division=dict(base,id='company:division',company_name='Division',product_names=['Model'],sourceArticles=[{'id':'a'}])
        rules={'checkedAt':'2026-09-15','records':[{'record_name':'Division','owner_company':'Parent','source_kind':'division','reviewed':True,'facts':[{'field':'owner_company','value':'Parent','url':'https://example.com','title':'Official','quote':'Division is part of Parent'}]}]}
        result=apply_reviewed_research([company,division],rules)
        self.assertEqual(result[0]['product_names'],['Model'])
        self.assertIn('Division',result[0]['aliases'])
        self.assertEqual(result[0]['sourceArticles'],[{'id':'a'}])
        self.assertEqual(apply_reviewed_research(result,rules),result)

    def test_full_review_requires_explicit_mode_and_shared_budget(self):
        tx=tag_news.load_taxonomy(str(ROOT/'config/taxonomy.json'))
        packet={'record_name':'X','sources':[{'url':'https://example.com','title':'Official','text':'Company X'}]}
        model=Mock(return_value=json.dumps({'entity_type':'company','facts':[]}))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):propose(tx,packet,folder,allow_paid=True,max_requests=73,llm_fn=model)
            Path(folder,'requests.json').write_text(json.dumps({'attempts':73,'limit':73}))
            with self.assertRaises(ValueError):propose(tx,packet,folder,allow_paid=True,max_requests=73,full_review=True,llm_fn=model)
            model.assert_not_called()

    def test_foundation_identity_survives_replay_without_product_reassignment(self):
        rules = {'checkedAt': '2026-09-14', 'records': [{
            'record_name': 'Tool', 'owner_company': 'Tool Foundation', 'reviewed': True,
            'owner_entity_type': 'foundation',
            'entity_type_evidence': {'url': 'https://example.com', 'quote': 'independent foundation', 'checkedAt': '2026-09-14'},
            'facts': [{'field': 'owner_company', 'value': 'Tool Foundation', 'url': 'https://example.com', 'title': 'Official', 'quote': 'Tool by Tool Foundation'}]}]}
        row = {'id': 'company:tool', 'company_name': 'Tool', 'aliases': [], 'product_names': [],
               'sourceArticles': [{'id': 'a'}], 'fieldSources': {}, 'firstSeenAt': '2026-09-13', 'lastSeenAt': '2026-09-13'}
        result = apply_reviewed_research([row], rules)
        self.assertEqual(result[0]['entityType'], 'foundation')
        self.assertEqual(result[0]['company_name'], 'Tool Foundation')
        self.assertEqual(result[0]['lastSeenAt'], row['lastSeenAt'])
        # A future extraction may classify it generically; reviewed type wins again.
        result[0]['entityType'] = 'company'
        replay = apply_reviewed_research(result, rules)
        self.assertEqual(replay[0]['entityType'], 'foundation')
        self.assertEqual(apply_reviewed_research(replay, rules), replay)

    def test_unnamed_collections_do_not_survive_cached_product_refresh(self):
        from company_index.products import normalize, refresh
        row = {'product_names': ['9款机器人本体', '4套行业解决方案', 'FF 91'],
               'productUpdates': [{'name': '9款机器人本体', 'articleId': 'a'}],
               'fieldSources': {'product_names': [{'value': '4套行业解决方案', 'articleId': 'b'}]}}
        refresh(row)
        self.assertEqual(row['product_names'], ['FF 91'])
        self.assertEqual(row['fieldSources']['product_names'], [])
        self.assertEqual(normalize([{'name': '9款机器人本体'}]), [])
        self.assertEqual(refresh(row), row)

    def test_country_fill_preserves_existing_value_and_evidence(self):
        rules = {'checkedAt':'2026-09-10','records':[{'record_name':'X','reviewed':True,'facts':[{'field':'country','value':'美国','url':'https://example.com','title':'Official','quote':'incorporated in Delaware'}]}]}
        row = {'company_name':'X','country':None,'fieldSources':{}}
        filled = apply_reviewed_research([row], rules)
        self.assertEqual(filled[0]['country'], '美国')
        self.assertEqual(filled[0]['fieldSources']['country'][0]['origin'], 'research')
        self.assertEqual(apply_reviewed_research(filled, rules), filled)
        row['country'] = '爱尔兰'
        result = apply_reviewed_research([row], rules)[0]
        self.assertEqual(result['country'], row['country'])
        self.assertEqual(result['fieldSources'], row['fieldSources'])

    def test_verified_owner_keeps_report_recency_and_other_company_integration(self):
        article = {'id': 'a', 'publishedAt': '2026-09-14T08:00:00+08:00', 'url': 'https://example.com/news', 'title': 'Product launch'}
        base = dict(aliases=[], product_names=[], fieldSources={}, sourceArticles=[article], firstSeenAt=article['publishedAt'], lastSeenAt=article['publishedAt'])
        product = dict(base, id='p', company_name='Product', entityType='product')
        integrator = dict(base, id='i', company_name='Integrator', productUpdates=[dict(name='Product', relationship='integrated', articleId='a')])
        rules = {'checkedAt': '2026-09-14', 'records': [{'record_name': 'Product', 'owner_company': 'Owner', 'owned_products': ['Product'], 'reviewed': True, 'facts': [{'field': 'owner_company', 'value': 'Owner', 'url': 'https://example.com/official', 'title': 'Official', 'quote': 'Product by Owner'}]}]}
        result = apply_reviewed_research([product, integrator], rules)
        owner = next(r for r in result if r['company_name'] == 'Owner')
        self.assertEqual(owner['productUpdates'][0]['relationship'], 'owned')
        self.assertEqual(owner['productUpdates'][0]['publishedAt'], article['publishedAt'])
        self.assertEqual(next(r for r in result if r['company_name'] == 'Integrator')['productUpdates'][0]['relationship'], 'integrated')
        self.assertEqual(apply_reviewed_research(result, rules), result)

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
            evidence = list(Path(folder).glob('*.response.json'))
            self.assertEqual(len(evidence), 1)
            self.assertEqual(json.loads(evidence[0].read_text(encoding='utf-8'))['response'], model.return_value)
            with self.assertRaisesRegex(ValueError, '不自动重试'):
                propose(tx,packet,folder,allow_paid=True,llm_fn=model)
            self.assertEqual(model.call_count, 1)

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
