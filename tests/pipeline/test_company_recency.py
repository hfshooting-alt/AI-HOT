import json
import unittest
from pathlib import Path
from company_index.entities import merge_entities

TX=json.loads((Path(__file__).resolve().parents[2]/'config/taxonomy.json').read_text(encoding='utf-8'))

class RecencyTest(unittest.TestCase):
    def test_old_backfill_does_not_overwrite_new_fact_and_latest_mention_moves_first(self):
        def article(aid, date):
            return dict(id=aid,publishedAt=date,title=aid,url='https://example.com/'+aid,sourceName='source',dims={})
        def extracted(name,business):
            return {'companies':[dict(company_name=name,aliases=[],product_names=[],industry_id='ai_model',business=business)]}
        new=article('new','2026-09-10T09:00:00+08:00')
        old=article('old','2026-09-10T00:00:00Z')
        rows=merge_entities([new],{'new':extracted('X','new fact')},{},TX)
        rows=merge_entities([old],{'old':extracted('X','old fact')},{'companies':rows},TX)
        self.assertEqual(rows[0]['business'],'new fact')
        self.assertEqual(rows[0]['updatedAt'],new['publishedAt'])
        later=article('later','2026-09-10T03:00:00Z')
        rows=merge_entities([later],{'later':extracted('X','updated fact')},{'companies':rows},TX)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['sourceArticles'][0]['id'],'later')
        self.assertEqual(rows[0]['updatedAt'],later['publishedAt'])
        self.assertEqual(rows[0]['business'],'updated fact')
        self.assertEqual(rows[0]['firstSeenAt'],old['publishedAt'])
