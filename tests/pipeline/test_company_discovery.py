import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from company_index.discovery import discover, reserve
from company_index.daily_research import enrich
from automation.runner import plan


class CompanyDiscoveryTest(unittest.TestCase):
    TX = {"model": {"model": "offline-research-model"}}

    def setUp(self):
        env=patch.dict("os.environ", {"COMPANY_DISCOVERY_QUOTA_READY":"1", "GITHUB_ACTIONS":""})
        env.start();self.addCleanup(env.stop)

    def client(self):
        c=Mock();c.available_credits.return_value=100
        c.create_crawl_task.return_value=SimpleNamespace(task_id='test',task_url='https://example.com/task')
        c.wait_for_structured_result.return_value={'evidence':[{'url':'https://example.com/legal'}]}
        c._request.return_value={'task':{'credit_usage':2,'status':'stopped'}}
        return c

    def test_day_quota_prevents_second_entity_and_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            reserve(d,'2026-09-15')
            c=self.client();r=discover({'id':'one','company_name':'One'},directory=d,client=c,day='2026-09-15')
            self.assertEqual(r['creditsUsed'],2)
            self.assertEqual(r['urls'],['https://example.com/legal'])
            again=discover({'id':'two','company_name':'Two'},directory=d,client=c,day='2026-09-15')
            self.assertEqual(again['status'],'quota_used');c.create_crawl_task.assert_called_once()

    def test_reservation_from_other_workflow_never_creates_task(self):
        with tempfile.TemporaryDirectory() as d:
            reserve(d,'2026-09-15',run_owner='another-run:1')
            c=self.client();r=discover({'id':'one','company_name':'One'},directory=d,client=c,day='2026-09-15')
            self.assertEqual(r['status'],'quota_used');c.create_crawl_task.assert_not_called()

    def test_missing_durable_quota_skips_without_creating(self):
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ',{'GITHUB_ACTIONS':'true','COMPANY_DISCOVERY_QUOTA_READY':'0'}):
            c=self.client()
            r=discover({'id':'one','company_name':'One'},directory=d,client=c)
            self.assertEqual(r['status'],'quota_unavailable');c.create_crawl_task.assert_not_called()

    def test_stop_recovers_links_and_never_retries_creation(self):
        with tempfile.TemporaryDirectory() as d:
            reserve(d,'2026-09-15');c=self.client()
            c.wait_for_structured_result.side_effect=RuntimeError('20 credits')
            c.read_stopped_results.return_value={'evidence':[{'url':'https://example.com/partial'}]}
            r=discover({'id':'one','company_name':'One'},directory=d,client=c,day='2026-09-15')
            self.assertEqual(r['status'],'stopped');self.assertEqual(len(r['urls']),1)
            c.stop_task.assert_called_once_with('test');c.create_crawl_task.assert_called_once()

    def test_discovered_link_flows_to_reader_and_model_without_overwriting(self):
        row={'id':'company:x','company_name':'X','country':None,'business':'Existing','fieldSources':{},'sourceArticles':[]}
        find=Mock(return_value={'status':'completed','urls':['https://example.com/legal']})
        read=Mock(return_value={'url':'https://example.com/legal','title':'Legal','text':'X in China'})
        model=Mock(return_value={'facts':[{'field':'country','value':'中国','url':'https://example.com/legal','title':'Legal','quote':'China'}]})
        with tempfile.TemporaryDirectory() as d:
            data=enrich({'companies':[row]}, self.TX, d, budget_dir=Path(d)/'budget', rules={}, discovery_fn=find, read_fn=read, propose_fn=model)
        read.assert_called_once_with('https://example.com/legal')
        self.assertEqual(data['companies'][0]['country'],'中国')
        self.assertEqual(data['companies'][0]['business'],'Existing')
        self.assertEqual(data['companies'][0]['fieldSources']['country'][0]['verificationStatus'],'provisional')

    def test_direct_full_disables_discovery_but_legacy_plan_remains_explicit(self):
        for mode in ('full', 'direct-only'):
            cmd=plan(Path('/root'),Path('/root/work/one/workspace'),'2026-09-15',combined=True,source_mode=mode)['overview']
            self.assertNotIn('--discover-company', cmd)
            self.assertIn('--research-full-review', cmd)
        legacy=plan(Path('/root'),Path('/root/work/one/workspace'),'2026-09-15',combined=True,source_mode='manus-only')['overview']
        self.assertIn('--discover-company', legacy)
        with self.assertRaisesRegex(ValueError, 'AIHOT'):
            plan(Path('/root'),Path('/root/work/one/workspace'),'2026-09-15',combined=True,source_mode='aihot-only')

    def test_product_ownership_stays_candidate_and_never_becomes_company_fields(self):
        row={'id':'company:tool','company_name':'Tool','fieldSources':{},'sourceArticles':[]}
        read=Mock(return_value={'url':'https://example.com','title':'About','text':'Company owns Tool'})
        model=Mock(return_value={'owner_company':'Company','facts':[{'field':'owner_company','value':'Company','url':'https://example.com','quote':'Company owns Tool','title':'About'}, {'field':'country','value':'美国','url':'https://example.com','quote':'US','title':'About'}]})
        find=Mock(return_value={'status':'completed','urls':['https://example.com']})
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[],'pendingEntities':[row]}, self.TX, d,budget_dir=Path(d)/'budget',rules={}, discovery_fn=find,read_fn=read,propose_fn=model)
        self.assertEqual(result['companies'],[])
        product=result['pendingEntities'][0]
        self.assertEqual(product['candidateOwners'][0]['name'],'Company')
        self.assertIsNone(product.get('country'))
