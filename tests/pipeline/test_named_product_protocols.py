import unittest
from company_index.products import is_named_product, refresh

class NamedProductProtocols(unittest.TestCase):
    def test_bare_protocols_are_not_products_but_named_tools_remain(self):
        for name in ['MCP', ' api ', 'SDK']:
            self.assertFalse(is_named_product(name))
        for name in ['Context7 MCP', 'OpenAI API', 'Hyper3D Rodin']:
            self.assertTrue(is_named_product(name))
    def test_cached_generic_names_and_all_their_product_evidence_are_removed(self):
        row = {'product_names':['MCP','Hyper3D Rodin'], 'productUpdates':[
            {'name':'MCP','articleId':'manus:a','publishedAt':'2026-09-22'},
            {'name':'Hyper3D Rodin','articleId':'manus:a','publishedAt':'2026-09-22'}],
            'fieldSources':{'product_names':[{'value':'MCP','articleId':'manus:a'}]}}
        refresh(row)
        self.assertEqual(row['product_names'], ['Hyper3D Rodin'])
        self.assertEqual(row['fieldSources']['product_names'], [])
