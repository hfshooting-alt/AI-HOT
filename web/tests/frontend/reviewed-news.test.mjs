import assert from 'node:assert/strict';
import test from 'node:test';
import { mergeReviewedNews, mergeReviewedCompanies } from '../../app/_lib/data/reviewed-news.mjs';

const item = {id:'manus:one', title:'模型发布', summary:'核验摘要', url:'https://example.com/one',
  publishedAt:'2026-09-17T15:50:00+08:00', classification:{autoFallback:false}};
const entry = {reviewed:true, reviewedAt:'2026-09-18T14:00:00+08:00',
  collectionWindow:{start:'2026-09-17T09:30:00+08:00',end:'2026-09-18T09:30:00+08:00'}, item};
const data = {schemaVersion:1, entries:[entry]};
test('company merge does not revive removed product names or count casing variants twice', () => {
  const company = {id:'company:one',company_name:'Owner',sourceArticles:[{id:item.id,publishedAt:item.publishedAt}],
    lastSeenAt:item.publishedAt,product_names:['Model'],
    productUpdates:[{articleId:item.id,name:'Model',publishedAt:item.publishedAt},
      {articleId:item.id,name:'Removed brand',publishedAt:item.publishedAt}]};
  const older = {...company, product_names:['MODEL'],
    productUpdates:[{articleId:item.id,name:'MODEL',publishedAt:item.publishedAt}]};
  const merged = mergeReviewedCompanies({companies:[company],stats:{}},
    {schemaVersion:1,entries:[{...entry,companies:[older]}]});
  assert.deepEqual(merged.companies[0].product_names,['Model']);
  assert.equal(merged.companies[0].productUpdates.length,1);
  assert.equal(merged.stats.productsTotal,1);
});
test('reviewed supplement preserves existing news, sorts, and does not mutate inputs', () => {
  const base = [{...item, id:'aihot:old', title:'旧新闻', url:'https://example.com/old', publishedAt:'2026-09-17T09:00:00+08:00'}];
  const before = JSON.stringify(base);
  assert.deepEqual(mergeReviewedNews(base,data,'2026-09-17T09:30:00+08:00').map(x=>x.id),['manus:one','aihot:old']);
  assert.equal(JSON.stringify(base),before);
});
test('rejects unaudited, failed classification, and out-of-window supplements', () => {
  for (const bad of [{...entry,reviewed:false},{...entry,reviewedAt:''},
    {...entry,item:{...item,classification:{autoFallback:true}}},
    {...entry,item:{...item,publishedAt:entry.collectionWindow.end}}]) {
    assert.equal(mergeReviewedNews([],{schemaVersion:1,entries:[bad]}).length,0);
  }
});
test('same-window batch deduplicates by id, URL and title; later batch retires supplement', () => {
  for (const duplicate of [item,{...item,id:'other'},{...item,id:'other',url:'https://example.com/copy'}]) {
    assert.deepEqual(mergeReviewedNews([duplicate],data,entry.collectionWindow.end),[duplicate]);
  }
  assert.equal(mergeReviewedNews([],data,'2026-09-19T09:30:00+08:00').length,0);
  assert.deepEqual(mergeReviewedNews([item],null),[item]);
});
test('company supplement preserves newer facts and daily counts while merging article evidence', () => {
  const company = {id:'company:one',company_name:'Canonical',aliases:['Brand'],sourceArticles:[{id:item.id,publishedAt:item.publishedAt}],
    lastSeenAt:item.publishedAt,latestReportAt:item.publishedAt,product_names:['Model'],productUpdates:[],business:'Reviewed',fieldSources:{business:[]}};
  const source = {companies:[{...company,company_name:'Brand',business:'Newer verified fact',sourceArticles:[]}],stats:{articlesProcessed:408}};
  const before = JSON.stringify(source);
  const merged = mergeReviewedCompanies(source,{schemaVersion:1,entries:[{...entry,companies:[company]}]});
  assert.equal(merged.companies.length,1);
  assert.equal(merged.companies[0].company_name,'Canonical');
  assert.equal(merged.companies[0].business,'Newer verified fact');
  assert.equal(merged.companies[0].sourceArticles[0].id,item.id);
  assert.equal(merged.stats.articlesProcessed,408);
  assert.equal(JSON.stringify(source),before);
  assert.deepEqual(mergeReviewedCompanies(source,null),source);
});
