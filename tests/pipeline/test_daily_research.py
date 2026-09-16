import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from company_index.daily_research import enrich, eligible_fact
from company_index.research import propose
from automation.runner import plan


def sample(name='X'):
    return {'id':'company:'+name,'company_name':name,'country':None,'fieldSources':{},
            'business':'已有业务','lastSeenAt':'2026-09-15','sourceArticles':[{'url':'https://example.com/'+name}]}


class DailyResearchTest(unittest.TestCase):
    TX = {"model": {"model": "offline-research-model"}}

    def test_financial_intentions_and_unsupported_team_details_are_rejected(self):
        self.assertIsNone(eligible_fact({'field':'total_funding','value':'拟募集15亿元人民币','quote':'首轮融资拟募集15亿元'},sample()))
        self.assertIsNone(eligible_fact({'field':'valuation','value':'独角兽','quote':'已跻身独角兽'},sample()))
        self.assertEqual(eligible_fact({'field':'team','value':'X CEO 张三；清华团队','quote':'X CEO 张三'},sample())['value'],'X CEO 张三')

    def test_isolated_failure_provisional_value_and_no_repeat(self):
        original={'companies':[sample('X'),sample('Y')]}
        def page(url):
            if url.endswith('/X'):raise ValueError('unavailable')
            return {'url':url,'title':'About','text':'Headquarters in China'}
        model=Mock(return_value={'facts':[{'field':'country','value':'中国','url':'https://example.com/Y','title':'About','quote':'China'},
                                         {'field':'business','value':'模型试图覆盖','url':'https://example.com/Y','title':'About','quote':'China'}]})
        with tempfile.TemporaryDirectory() as d:
            result=enrich(original,self.TX,d,read_fn=page,propose_fn=model,rules={})
            self.assertIsNone(result['companies'][0]['country'])
            row=result['companies'][1]
            self.assertEqual(row['country'],'中国')
            self.assertEqual(row['business'],'已有业务')
            self.assertEqual(row['fieldSources']['country'][0]['verificationStatus'],'provisional')
            self.assertEqual(row['sourceArticles'],original['companies'][1]['sourceArticles'])
            # 成功和失败输入都不会因为补过字段而重复请求。
            unchanged=copy.deepcopy(result)
            repeat=enrich(unchanged,self.TX,d,read_fn=Mock(side_effect=ValueError),propose_fn=model,rules={})
            self.assertEqual(repeat['knownLinkResearch']['skippedUnchanged'],2)

    def test_budget_caps_requests_and_keeps_remainder(self):
        page=lambda u:{'url':u,'title':'About','text':'Evidence'}
        model=Mock(return_value={'facts':[]})
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[sample(str(i)) for i in range(8)]},self.TX,d,read_fn=page,propose_fn=model,rules={})
            self.assertEqual(model.call_count,5)
            self.assertEqual(result['knownLinkResearch']['deferred'],3)
            second=enrich(result,self.TX,d,read_fn=page,propose_fn=model,rules={})
            self.assertEqual(second['knownLinkResearch']['attempted'],3)

    def test_one_invalid_quote_does_not_discard_valid_fact(self):
        model=Mock(return_value='{"entity_type":"company","owner_company":null,"facts":[{"field":"country","value":"中国","source_index":0,"quote":"China"},{"field":"team","value":"Wrong","source_index":0,"quote":"not present"}]}')
        packet={'record_name':'X','sources':[{'url':'https://example.com','title':'About','text':'China'}]}
        with tempfile.TemporaryDirectory() as d:
            result=propose(self.TX,packet,d,allow_paid=True,llm_fn=model,isolate_invalid=True)
            self.assertEqual(len(result['facts']),1)
            self.assertEqual(result['rejectedFacts'],1)

    def test_daily_plan_runs_research_inside_overview_before_publication(self):
        commands=plan(Path('/repo'),Path('/repo/work/run/workspace'),'2026-09-15',combined=True)
        self.assertIn('--known-link-research',commands['overview'])
        self.assertNotIn('--known-link-research',commands['news'])
