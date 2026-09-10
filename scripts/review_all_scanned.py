"""Explicit full DeepSeek review of an existing snapshot; never calls Manus or promotes production."""
import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import tag_news
from llm_common import call_llm, parse_output
from company_index.inputs import load_articles, load_previous
from company_index.extraction import extract_one, cache_key
from company_index.entities import merge_entities
from company_index.identity import apply_reviewed_research
from company_index.output import atomic_write, assemble, validate
from company_index.config import now_bj_iso


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', required=True)
    p.add_argument('--feed', required=True)
    p.add_argument('--previous', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--allow-paid', action='store_true')
    p.add_argument('--retry-failed', action='store_true', help='Explicitly retry failed extraction, reusing successful classification')
    args = p.parse_args()
    if not args.allow_paid:
        p.error('--allow-paid is required')
    out = Path(args.output).resolve()
    if not out.is_relative_to(Path('work').resolve()):
        p.error('output must be under work/')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['LLM_USAGE_LOG'] = str(out / 'usage.jsonl')
    tx = tag_news.load_taxonomy('config/taxonomy.json')
    tx['model']['timeout_seconds'] = 90
    tx['companyOverview']['timeout_seconds'] = 90
    articles = load_articles(args.snapshot, args.feed, 'work/manus/ten-am', tx)
    if not articles:
        p.error('no scanned articles; candidate not updated')
    print(f'FULL_REVIEW articles={len(articles)} model={tx["model"]["model"]}', flush=True)
    cache = out / 'articles'
    cache.mkdir(exist_ok=True)
    def review(a):
        key = hashlib.sha256((cache_key(tx,a) + tag_news.cache_prefix(tx)).encode()).hexdigest()
        path = cache / (key + '.json')
        previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if previous and not (args.retry_failed and previous.get('status') == 'failed'):
            return a['id'], previous
        if previous:
            atomic_write(path.with_suffix('.previous.json'),previous)
        atomic_write(path, {'status':'reserved', 'articleId':a['id']})
        result = {'articleId':a['id'], 'title':a['title']}
        try:
            tag = previous.get('classification')
            if not tag or tag.get('autoFallback'):
                system, user = tag_news.build_prompt(tx, a['title'], a['content_text'][:5000])
                tag = tag_news.validate(tx, parse_output(call_llm(tx,system,user,timeout_seconds=90,operation='full_tag_review')))
            result['classification'] = tag
            if tag['autoFallback']:
                raise ValueError('invalid classification')
            result['extraction'] = extract_one(tx,a,lambda tx,s,u,**kw:call_llm(tx,s,u,**kw,max_tokens=8192,operation='full_company_review'))
            result['status'] = result['extraction']['status']
        except Exception as exc:
            result.update(status='failed', error=str(exc)[:160])
        atomic_write(path,result)
        return a['id'], result
    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for f in as_completed([pool.submit(review,a) for a in articles]):
            aid, value = f.result()
            results[aid] = value
            if len(results)%25 == 0: print(f'reviewed={len(results)}/{len(articles)}',flush=True)
    extracts = {aid:v.get('extraction',{'status':'failed','companies':[]}) for aid,v in results.items()}
    companies = apply_reviewed_research(merge_entities(articles,extracts,load_previous(args.previous),tx))
    complete = sum(v.get('status')=='complete' for v in results.values())
    stats = dict(articlesProcessed=len(articles),articlesComplete=complete,articlesFailed=len(articles)-complete,
                 companiesTotal=len(companies),productsTotal=sum(len(c['product_names']) for c in companies))
    overview = assemble(companies,stats,now_bj_iso())
    overview['coverageNote'] = f'当前已扫描文章全量模型复核：{complete}/{len(articles)}篇成功；按最新报道时间更新公司，字段保留报道及官网证据。'
    validate(overview,tx)
    atomic_write(out/'company-overview.json',overview)
    snapshot = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    by_url = {a['url']:results[a['id']] for a in articles}
    changes=[]
    for item in (snapshot.get('all') or {}).get('items',[]):
        r = results.get(item['id']) or results.get('aihot:'+str(item['id'])) or by_url.get(item.get('url')) or {}
        tag = r.get('classification')
        if tag and not tag.get('autoFallback'):
            item['classification'] = tag_news.to_display(tx,tag)
            item['classificationOrigin'] = 'deepseek-review'
            item['categoryUnclassified'] = False
    for view in ('daily','weekly'):
        sections = snapshot.get(view,{}).get('sections',[])
        if not sections: continue
        grouped={}
        for sec in sections:
            for item in sec.get('items',[]):
                r = results.get(item['id']) or by_url.get(item.get('url')) or {}
                tag = r.get('classification')
                if tag and not tag.get('autoFallback'):
                    previous=item.get('classification')
                    item['classification']=tag_news.to_display(tx,tag)
                    item['classificationOrigin']='deepseek-review'
                    item['categoryUnclassified']=False
                    if previous != item['classification']:
                        changes.append({'id':item['id'],'title':item['title'],'before':previous,'after':item['classification']})
                classification=item.get('classification') or {}
                label=classification.get('catLabel') or sec.get('label') or '泛行业新闻'
                bucket=grouped.setdefault(label,dict(sec,items=[]))
                bucket['label']=label
                bucket['items'].append(item)
                bucket['count']=len(bucket['items'])
        snapshot[view]['sections']=list(grouped.values())
    atomic_write(out/'snapshot.json',snapshot)
    atomic_write(out/'review-report.json',{'stats':stats,'changes':changes,'failures':[v for v in results.values() if v.get('status')!='complete']})
    print(json.dumps(stats,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
