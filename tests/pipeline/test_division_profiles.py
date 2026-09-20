import unittest

from company_index.entities import entity_id, merge_entities
from company_index.identity import apply_reviewed_research
from funding.companies import normalize_company_key


class DivisionProfilesTest(unittest.TestCase):
    TX = {'dimensions': {'industry': {'values': [{'id': 'ai_model', 'label': 'AI模型'}]}}}

    def row(self, name, **updates):
        value = dict(id=entity_id(normalize_company_key(name)), company_name=name,
                     entityType='company', aliases=[], product_names=[], fieldSources={},
                     sourceArticles=[], dims={'行业': '其他AI应用', '国家/地区': '美国'},
                     firstSeenAt='2026-09-01T09:30:00+08:00', lastSeenAt='2026-09-01T09:30:00+08:00')
        value.update(updates)
        return value

    def rules(self, division='Microsoft AI', owner='微软'):
        return {'checkedAt': '2026-09-20', 'records': [{'record_name': division,
            'owner_company': owner, 'source_kind': 'division', 'reviewed': True,
            'facts': [{'field': 'owner_company', 'value': owner, 'quote': division+' is a team within '+owner,
                       'url': 'https://example.com/article', 'title': 'Ownership evidence'}]}]}

    def article(self, aid='new', day='20'):
        return {'id': aid, 'title': 'Team update', 'url': 'https://example.com/'+aid,
                'publishedAt': f'2026-09-{day}T10:00:00+08:00'}

    def test_reviewed_division_avoids_parent_alias_before_identity_merge(self):
        for division, owner in [('Microsoft AI', '微软'), ('Google Brain', 'Google'), ('Nexa AI', '高通')]:
            with self.subTest(division=division):
                parent = self.row(owner, aliases=[division], business='Parent business', country='美国', founded='1975')
                article = self.article()
                item = {'company_name': division, 'aliases': [owner], 'business': 'Team business',
                        'country': '英国', 'founded': '2024', 'industry_id': 'ai_model', 'product_names': ['Team Model']}
                rules = self.rules(division, owner)
                rows = merge_entities([article], {'new': {'companies': [item]}}, {'companies': [parent]}, self.TX, rules)
                self.assertEqual(len(rows), 2)
                self.assertEqual(next(r for r in rows if r['company_name']==owner)['business'], 'Parent business')
                merged = apply_reviewed_research(rows, rules)
                self.assertEqual(len(merged), 1)
                rec = merged[0]
                self.assertEqual((rec['business'], rec['country'], rec['founded']), ('Parent business', '美国', '1975'))
                self.assertEqual(rec['brandProfiles'][division]['business'], 'Team business')
                self.assertEqual(rec['product_names'], ['Team Model'])
                self.assertNotIn(division, rec['product_names'])
                self.assertEqual({a['id'] for a in rec['sourceArticles']}, {'new'})
                self.assertEqual(parent['business'], 'Parent business')

    def test_repeated_division_update_restores_brand_history_and_does_not_hijack_parent(self):
        rules = self.rules(); division = self.row('Microsoft AI', business='Old team business', product_names=['Old Model'],
                                                   sourceArticles=[self.article('old', '18')])
        parent = self.row('微软', aliases=['Microsoft AI', 'Microsoft'], business='Parent business',
                          brandProfiles={'Microsoft AI': division})
        team_article, parent_article = self.article(), self.article('parent', '21')
        extracts = {'new': {'companies': [{'company_name': 'Microsoft AI', 'aliases': ['Microsoft'],
                                          'business': 'New team business', 'product_names': ['New Model']}]},
                    'parent': {'companies': [{'company_name': 'Microsoft', 'business': 'New parent business'}]}}
        rows = merge_entities([team_article, parent_article], extracts, {'companies': [parent]}, self.TX, rules)
        merged = apply_reviewed_research(rows, rules)
        rec = merged[0]
        self.assertEqual(len(merged), 1)
        self.assertEqual(rec['business'], 'New parent business')
        profile = rec['brandProfiles']['Microsoft AI']
        self.assertEqual(profile['id'], division['id'])
        self.assertEqual(profile['business'], 'New team business')
        self.assertEqual(set(profile['product_names']), {'Old Model', 'New Model'})
        self.assertEqual({a['id'] for a in profile['sourceArticles']}, {'old', 'new'})
        replay = apply_reviewed_research(merge_entities([team_article, parent_article], extracts, {'companies': merged}, self.TX, rules), rules)
        self.assertEqual(replay, merged)
        self.assertEqual(parent['brandProfiles']['Microsoft AI']['business'], 'Old team business')

    def test_ordinary_alias_and_unreviewed_division_keep_normal_routing(self):
        parent = self.row('微软', aliases=['Microsoft AI'], business='Old business')
        article = self.article(); extracts = {'new': {'companies': [{'company_name': 'Microsoft AI', 'business': 'New business'}]}}
        for change in ({'source_kind':'company_alias'}, {'reviewed':False}, {'facts':[]}):
            rules = self.rules(); rules['records'][0].update(change)
            with self.subTest(change=change):
                rows = merge_entities([article], extracts, {'companies':[parent]}, self.TX, rules)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['id'], parent['id'])
                self.assertEqual(rows[0]['business'], 'New business')

    def test_division_matches_primary_name_without_splitting_ordinary_parent_alias(self):
        parent = self.row('微软', aliases=['Microsoft AI', 'Microsoft'], business='Old business')
        article = self.article(); extracts = {'new': {'companies': [{'company_name': 'Microsoft',
                         'aliases': ['Microsoft AI'], 'business': 'New parent business'}]}}
        rows = merge_entities([article], extracts, {'companies':[parent]}, self.TX, self.rules())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['business'], 'New parent business')
        self.assertNotIn('brandProfiles', rows[0])

    def test_normalized_division_spelling_retains_review_rule_name(self):
        parent = self.row('微软', aliases=['MicrosoftAI'], business='Parent business')
        existing = self.row('MicrosoftAI', business='Old team business')
        article = self.article()
        extracts = {'new': {'companies': [{'company_name': 'MicrosoftAI', 'business': 'Team business'}]}}
        rows = merge_entities([article], extracts, {'companies':[parent, existing]}, self.TX, self.rules())
        merged = apply_reviewed_research(rows, self.rules())
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['business'], 'Parent business')
        self.assertEqual(merged[0]['brandProfiles']['Microsoft AI']['id'], existing['id'])
