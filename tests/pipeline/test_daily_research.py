import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from company_index.daily_research import enrich as durable_enrich, eligible_fact
from company_index.research import propose
from automation.runner import plan
from llm_failures import LLMRequestError


def enrich(data, tx, directory, **kwargs):
    kwargs.setdefault('budget_dir', Path(directory) / 'budget')
    return durable_enrich(data, tx, directory, **kwargs)


def sample(name='X'):
    return {'id':'company:'+name,'company_name':name,'country':None,'fieldSources':{},
            'business':'已有业务','lastSeenAt':'2026-09-15','sourceArticles':[{'url':'https://example.com/'+name}]}


class DailyResearchTest(unittest.TestCase):
    TX = {"model": {"model": "offline-research-model"}}

    def setUp(self):
        env = patch.dict('os.environ', {'GITHUB_ACTIONS': ''})
        env.start(); self.addCleanup(env.stop)
        clock = patch('company_index.daily_research.now_bj_iso', return_value='2026-09-20T12:00:00+08:00')
        clock.start()
        self.addCleanup(clock.stop)

    def test_new_source_page_is_read_before_echoed_news_links(self):
        row = sample()
        row['sourceArticles'] = [{'url':'https://news.example/a'}, {'url':'https://news.example/b'}]
        discovery = Mock(return_value={'status':'completed','urls':[
            'https://news.example/a','https://news.example/b','https://company.example/about']})
        reader = Mock(side_effect=lambda url: {'url':url,'title':'Page','text':'Evidence'})
        with tempfile.TemporaryDirectory() as d:
            result = enrich({'companies':[row]},self.TX,d,rules={},read_fn=reader,
                            propose_fn=Mock(return_value={'facts':[]}),discovery_fn=discovery)
        self.assertEqual(reader.call_args_list[0].args[0], 'https://company.example/about')
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(result['knownLinkResearch']['attempted'], 1)

    def test_research_order_compares_instants_not_offset_text(self):
        older,newer=sample('older'),sample('newer')
        older['lastSeenAt']='2026-09-16T09:00:00+08:00'
        newer['lastSeenAt']='2026-09-16T02:00:00Z'
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[older,newer]},self.TX,d,rules={},max_requests=1,
                read_fn=lambda u:{'url':u,'title':'Page','text':'Evidence'},
                propose_fn=Mock(return_value={'facts':[]}))
        self.assertEqual(result['knownLinkResearch']['records'][0]['name'],'newer')

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
            self.assertEqual(second['knownLinkResearch']['attempted'],0)
            self.assertTrue(second['knownLinkResearch']['dailyLimitReached'])
            self.assertEqual(second['knownLinkResearch']['skippedUnchanged'],5)
            with patch('company_index.daily_research.now_bj_iso', return_value='2026-09-21T12:00:00+08:00'):
                next_day=enrich(second,self.TX,d,read_fn=page,propose_fn=model,rules={})
            self.assertEqual(next_day['knownLinkResearch']['attempted'],3)

    def test_basic_profile_and_pending_ownership_precede_financial_only(self):
        financial=sample('financial')
        financial.update(country='中国', founded='2020', team='Team', lastSeenAt='2026-09-20')
        basic=sample('basic');basic['lastSeenAt']='2026-09-18T12:00:00+08:00'
        pending={**financial, 'id':'company:pending', 'company_name':'pending',
                 'investors':'Fund', 'total_funding':'1亿美元', 'valuation':'2亿美元',
                 'lastSeenAt':'2026-09-19T12:00:00+08:00'}
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[financial,basic],'pendingEntities':[pending]},self.TX,d,
                rules={},read_fn=lambda u:{'url':u,'text':'Evidence'},propose_fn=Mock(return_value={'facts':[]}))
        report=result['knownLinkResearch']
        self.assertEqual([r['name'] for r in report['records']],['pending','basic','financial'])
        self.assertEqual(report['queue']['basicProfile'],1)
        self.assertEqual(report['queue']['pendingOwnership'],1)
        self.assertEqual(report['queue']['financialOnly'],1)
        self.assertEqual(report['records'][0]['missingFields'],['owner_company'])

    def test_discovery_selection_stays_first_in_priority_queue(self):
        newest,selected=sample('newest'),sample('selected')
        newest['lastSeenAt']='2026-09-20';selected['lastSeenAt']='2026-09-18'
        data={'companies':[newest,selected],'companyDiscovery':{'history':{newest['id']:{'urls':[]}}}}
        with tempfile.TemporaryDirectory() as d:
            result=enrich(data,self.TX,d,rules={},max_requests=1,
                discovery_fn=Mock(return_value={'status':'completed','urls':['https://company.example/about']}),
                read_fn=lambda u:{'url':u,'text':'Evidence'},propose_fn=Mock(return_value={'facts':[]}))
        report=result['knownLinkResearch']
        self.assertEqual(report['records'][0]['id'],selected['id'])
        self.assertEqual(report['queue']['discoverySelectedId'],selected['id'])

    def test_no_supported_fields_and_safe_errors_are_traceable_in_state(self):
        def page(url):
            if url.endswith('/page-fail'):raise TimeoutError('private-page-response')
            return {'url':url,'text':'Evidence'}
        def model(tx,packet,*args,**kwargs):
            if packet['record_name']=='model-fail':raise ValueError('字段缺少逐字来源证据，拒绝写入')
            return {'facts':[], 'rejectedFacts':2}
        rows=[sample(name) for name in ['page-fail','no-fields','model-fail']]
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':rows},self.TX,d,rules={},read_fn=page,propose_fn=model)
        report=result['knownLinkResearch'];events=report['records']
        self.assertEqual([e['status'] for e in events],
                         ['no_readable_page','completed_no_supported_fields','model_or_evidence_failed'])
        self.assertEqual(report['attempted'],2);self.assertEqual(report['failed'],2)
        self.assertFalse(report['circuitOpen'])
        self.assertEqual(events[0]['pageResults'][0]['failureType'],'timeout')
        self.assertEqual(events[2]['errorType'],'ValueError')
        self.assertEqual(events[2]['error']['category'],'content')
        for event in events:
            self.assertIn(event,list(result['knownLinkResearchState'].values()))
            for field in ('id','name','urls','missingFields','filledFields','checkedAt','modelAttempted'):
                self.assertIn(field,event)
        self.assertNotIn('private-',json.dumps(result))
        self.assertNotIn('profileUpdatedAt',result['companies'][1])

    def test_failed_page_is_not_retried_for_another_company(self):
        first,second=sample('first'),sample('second')
        for row in (first,second):row['sourceArticles']=[{'url':'https://example.com/shared'}]
        reader=Mock(side_effect=ValueError('页面正文不足'));model=Mock()
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[first,second]},self.TX,d,rules={},read_fn=reader,propose_fn=model)
        reader.assert_called_once();model.assert_not_called()
        self.assertTrue(result['knownLinkResearch']['records'][1]['pageResults'][0]['cached'])
        self.assertEqual(result['knownLinkResearch']['records'][0]['pageResults'][0]['failureType'],'insufficient_content')

    def test_daily_limits_cover_five_entities_and_ten_pages_even_on_failure(self):
        rows=[sample(str(i)) for i in range(8)]
        for row in rows:row['sourceArticles'].append({'url':row['sourceArticles'][0]['url']+'/about'})
        reader=Mock(side_effect=TimeoutError('private'));model=Mock()
        with tempfile.TemporaryDirectory() as d:
            first=enrich({'companies':rows},self.TX,d,rules={},read_fn=reader,propose_fn=model)
            repeat=enrich(first,self.TX,d,rules={},read_fn=reader,propose_fn=model)
        self.assertEqual(reader.call_count,10);model.assert_not_called()
        self.assertEqual(first['knownLinkResearch']['dailyUsageAfter'],{'entities':5,'pages':10,'requests':0})
        self.assertEqual(repeat['knownLinkResearch']['deferred'],3)
        self.assertTrue(repeat['knownLinkResearch']['dailyLimitReached'])

    def test_legacy_unknown_states_reserve_capacity_without_claiming_success(self):
        states={'old-'+str(i):{'checkedAt':value,'status':'completed'}
                for i,value in enumerate([None,'invalid',{},[],9])}
        reader,model=Mock(),Mock()
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[sample()], 'knownLinkResearchState':states},self.TX,d,
                rules={},read_fn=reader,propose_fn=model)
        reader.assert_not_called();model.assert_not_called()
        report=result['knownLinkResearch']
        self.assertEqual(report['unknownDateReservations'],5)
        self.assertEqual(report['queue']['legacyStateEntries'],5)
        self.assertEqual(report['attempted'],0);self.assertEqual(report['filled'],0)
        self.assertTrue(report['dailyLimitReached'])
        self.assertEqual(result['knownLinkResearchState'],states)

    def test_daily_budget_uses_beijing_day_for_legacy_entries(self):
        states={'legacy':{'checkedAt':'2026-09-19T17:00:00Z','status':'completed'}}
        model=Mock(return_value={'facts':[]})
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[sample(str(i)) for i in range(6)],'knownLinkResearchState':states},
                self.TX,d,rules={},read_fn=lambda u:{'url':u,'text':'Evidence'},propose_fn=model)
        self.assertEqual(model.call_count,4)
        self.assertEqual(result['knownLinkResearch']['dailyUsageBefore'],{'entities':1,'pages':2,'requests':1})

    def test_system_failure_stops_queue_and_saved_failure_stays_visible(self):
        rows=[sample(str(i)) for i in range(6)]
        model=Mock(side_effect=LLMRequestError('authentication',401))
        reader=Mock(side_effect=lambda u:{'url':u,'text':'Evidence'})
        with tempfile.TemporaryDirectory() as d:
            first=enrich({'companies':rows},self.TX,d,rules={},read_fn=reader,propose_fn=model)
            repeat=enrich(first,self.TX,d,rules={},read_fn=reader,propose_fn=model)
        model.assert_called_once();reader.assert_called_once()
        for result in (first,repeat):
            report=result['knownLinkResearch']
            self.assertTrue(report['circuitOpen'])
            self.assertEqual(report['circuitReason']['category'],'authentication')
            self.assertEqual(report['deferred'],5)
            self.assertTrue(all(r['reason']=='model_circuit' for r in report['notAttempted']))
        self.assertEqual(repeat['knownLinkResearch']['skippedUnchanged'],1)
        self.assertEqual(len(repeat['knownLinkResearchState']),1)

    def test_completed_fields_survive_later_system_failure(self):
        model=Mock(side_effect=[{'facts':[{'field':'country','value':'中国','url':'https://example.com/a',
            'title':'About','quote':'China'}]},LLMRequestError('payment',402)])
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[sample(str(i)) for i in range(4)]},self.TX,d,rules={},
                read_fn=lambda u:{'url':u,'text':'China'},propose_fn=model)
        self.assertEqual(model.call_count,2)
        self.assertEqual(result['companies'][0]['country'],'中国')
        self.assertEqual(result['knownLinkResearch']['records'][0]['status'],'completed')
        self.assertEqual(result['knownLinkResearch']['records'][0]['filledFields'],['country'])
        self.assertTrue(result['knownLinkResearch']['circuitOpen'])

    def test_consecutive_network_failures_trip_but_evidence_failures_do_not(self):
        for error,expected,stopped in [(TimeoutError('private'),3,True),
                (ValueError('字段缺少逐字来源证据，拒绝写入'),5,False)]:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as d:
                model=Mock(side_effect=error)
                result=enrich({'companies':[sample(str(i)) for i in range(6)]},self.TX,d,rules={},
                    read_fn=lambda u:{'url':u,'text':'Evidence'},propose_fn=model)
                self.assertEqual(model.call_count,expected)
                self.assertEqual(result['knownLinkResearch']['circuitOpen'],stopped)
                if stopped:
                    repeat=enrich(result,self.TX,d,rules={},
                        read_fn=lambda u:{'url':u,'text':'Evidence'},propose_fn=model)
                    self.assertEqual(model.call_count,expected)
                    self.assertTrue(repeat['knownLinkResearch']['circuitOpen'])

    def test_real_proposal_protocol_failures_stop_after_three_requests(self):
        for response in ('private-invalid-response', '{"entity_type":"company","facts":"wrong"}'):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as d:
                model=Mock(return_value=response)
                def proposal(tx,packet,directory,**kwargs):
                    return propose(tx,packet,directory,llm_fn=model,**kwargs)
                result=enrich({'companies':[sample(str(i)) for i in range(6)]},self.TX,d,rules={},
                    read_fn=lambda u:{'url':u,'title':'Page','text':'Evidence'},propose_fn=proposal)
                report=result['knownLinkResearch']
                self.assertEqual(model.call_count,3)
                self.assertTrue(report['circuitOpen'])
                self.assertEqual(report['circuitReason']['category'],'invalid_response')
                self.assertEqual(report['deferred'],3)
                self.assertEqual(json.loads((Path(d)/'budget/model-cache/2026-09-20/requests.json').read_text())['attempts'],3)
                self.assertNotIn('private-invalid-response',json.dumps(result))

    def test_json_decode_errors_are_protocol_failures_not_content(self):
        model=Mock(side_effect=json.JSONDecodeError('private-json-error','private-response',0))
        with tempfile.TemporaryDirectory() as d:
            result=enrich({'companies':[sample(str(i)) for i in range(6)]},self.TX,d,rules={},
                read_fn=lambda u:{'url':u,'text':'Evidence'},propose_fn=model)
        self.assertEqual(model.call_count,3)
        self.assertEqual(result['knownLinkResearch']['circuitReason']['category'],'invalid_response')
        self.assertNotIn('private-',json.dumps(result))

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
