"""Sample source acquisition independently from full-window coverage; never writes production feeds."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from manus_source.client import ManusClient
from manus_source.config import Settings, load_sources, render_sources_block
from manus_source.runner import canary_slug
from manus_source.window import ten_am_window
from company_index.output import atomic_write

ROOT=Path(__file__).resolve().parents[1]
SCHEMA={'type':'object','properties':{'articles':{'type':'array','items':{'type':'object','properties':{k:{'type':'string'} for k in ('title','url','publishedAt','publisher','timeEvidence')},'required':['title','url','publishedAt','publisher','timeEvidence'],'additionalProperties':False}},'reason':{'type':'string'}},'required':['articles','reason'],'additionalProperties':False}
SCHEMA['properties']['observations']=SCHEMA['properties']['articles']
SCHEMA['required'].append('observations')


def validate_sample(payload, source, window, require_window=True):
    articles=payload.get('articles',[])
    if not 1 <= len(articles) <= 2:
        return False
    start,end=(datetime.fromisoformat(window[k]) for k in ('start','end'))
    names=[source['account_name'],*source.get('verified_display_names',[])]
    for a in articles:
        try:
            dt=datetime.fromisoformat(a['publishedAt'].replace('Z','+00:00'))
            if not dt.tzinfo or (require_window and not start <= dt < end): return False
            if urlparse(a['url']).scheme not in ('http','https') or not urlparse(a['url']).netloc: return False
            host=urlparse(a['url']).hostname or ''
            expected=urlparse(source['home_url']).hostname or ''
            if host != expected and not (expected.endswith('jiqizhixin.com') and host.endswith('.jiqizhixin.com')): return False
            if a['publisher'] not in names or not a['title'].strip() or not a['timeEvidence'].strip(): return False
        except (KeyError,ValueError,TypeError): return False
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--accounts',nargs='+',required=True)
    p.add_argument('--date',required=True)
    p.add_argument('--allow-paid',action='store_true')
    args=p.parse_args()
    if not args.allow_paid: p.error('--allow-paid required')
    cfg=Settings.from_environment(ROOT)
    groups=load_sources(cfg.sources_path)
    available={s['account_name']:s for group in groups.values() for s in group}
    if any(n not in available for n in args.accounts): p.error('unknown source')
    names=list(dict.fromkeys(args.accounts))
    window=ten_am_window(args.date)
    out=ROOT/'work/source-capability'/args.date
    out.mkdir(parents=True,exist_ok=True)
    def probe(name):
        source=available[name]
        path=out/(canary_slug(name)+'.json')
        if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
        record={'accountName':name,'sourceIdentity':source,'collectionWindow':window,'capability':'unconfirmed','coverage':'unconfirmed','createAttempts':0}
        atomic_write(path,record)
        client=ManusClient(api_key=cfg.manus_api_key,agent_profile='manus-1.6-lite',poll_seconds=5,timeout_seconds=240,register_grace_seconds=30,create_retries=0)
        task=None
        try:
            if client.available_credits()<20: raise ValueError('balance below reserve')
            prompt=f'''仅测试媒体文章获取能力，不做全天扫描。入口：\n{render_sources_block([source])}\n窗口 {window['start']}（含）到 {window['end']}（不含）。仅沿该配置入口核实身份（允许配置显示名），列表最多等待30秒、选择图文一次、原URL重开一次。读取详情核实发布者及年月日时分，将时间原文抄入timeEvidence；禁止凭相对时间或URL推断。找到1篇合格窗口内文章即可立即返回，最多2篇，不再寻找24小时边界。遇到明确早于窗口文章而无窗口内样本，返回空数组并说明不能确认能力。机器之心官网只接受署名机器之心，不收其他机构。只返回JSON articles:[title,url,publishedAt含时区,publisher,timeEvidence],reason。明确禁止打开mp.weixin.qq.com，不换入口。'''
            prompt+='\n补充：最多两篇指最终合格样本数，不是只检查前两篇。详情时间晚于窗口结束时继续沿原列表顺序核实，不能因此宣称窗口无文章。将实际已核实但超窗的详情放入 observations（相同字段，最多2篇）；窗口内样本放 articles。没有窗口内样本时仍返回 observations，明确区分读取能力与窗口匹配。'
            record['createAttempts']=1
            atomic_write(path,record)
            task=client.create_crawl_task(prompt,'capability',args.date,f'媒体样本验证 {name}','只取一个窗口内合格样本后立即结束，不检查完整边界。',SCHEMA)
            record['taskId']=task.task_id
            atomic_write(path,record)
            payload=client.wait_for_structured_result(task.task_id,observed_credit_limit=20)
            record['sample']=payload
            accessible = payload if payload.get('articles') else {'articles':payload.get('observations',[])}
            record['capability']='passed' if validate_sample(accessible,source,window,False) else 'unconfirmed'
            record['sampleWindowVerified']=validate_sample(payload,source,window)
            record['evidenceType']='structured_sample'
        except Exception as exc:
            record['reason']=str(exc)[:250]
            if task:
                try:
                    client.stop_task(task.task_id)
                    record['stopSucceeded']=True
                except Exception as stop:
                    record['stopSucceeded']=False
                    record['stopError']=str(stop)[:160]
        finally:
            if task:
                try:
                    detail=client._request('GET','task.detail?task_id='+task.task_id)
                    record['creditsUsed']=(detail.get('task') or {}).get('credit_usage')
                except Exception: pass
            atomic_write(path,record)
        print(json.dumps({k:record.get(k) for k in ('accountName','capability','coverage','reason','creditsUsed','stopSucceeded')},ensure_ascii=False),flush=True)
        return record
    records=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(probe,n) for n in names]): records.append(f.result())
    atomic_write(out/'report.json',{'sources':records,'window':window})


if __name__=='__main__': main()
