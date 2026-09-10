import json
import tempfile
import unittest
from pathlib import Path
from manus_source.config import load_sources, render_sources_block


class DisplayNamesTest(unittest.TestCase):
    def test_alias_does_not_replace_canonical_identity(self):
        source = {'account_name': 'ZPotential', 'platform': 'Tencent News',
                  'home_url': 'https://example.com/author/1',
                  'verified_display_names': ['ZPotentials']}
        block = render_sources_block([source])
        self.assertIn('媒体名称：ZPotential\n', block)
        self.assertIn('已核实页面显示名：ZPotentials', block)
        self.assertEqual(source['account_name'], 'ZPotential')

    def test_bad_alias_type_rejected_before_request(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sources.json'
            path.write_text(json.dumps({'groups': {'group_a': [{
                'account_name': 'A', 'platform': 'Tencent News',
                'home_url': 'https://example.com', 'verified_display_names': 'A'}]}}), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                load_sources(path)
