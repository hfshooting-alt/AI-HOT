import unittest
from probe_source_capability import validate_sample
from manus_source.window import ten_am_window

class CapabilityTest(unittest.TestCase):
    def test_acquisition_does_not_imply_window_coverage(self):
        source={'account_name':'Media','home_url':'https://news.qq.com/author'}
        article={'title':'Sample','url':'https://news.qq.com/article','publisher':'Media',
                 'publishedAt':'2026-09-10T13:19:00+08:00','timeEvidence':'2026-09-10 13:19'}
        window=ten_am_window('2026-09-10')
        self.assertTrue(validate_sample({'articles':[article]},source,window,False))
        self.assertFalse(validate_sample({'articles':[article]},source,window))
        article['publishedAt']='2026-09-10T09:19:00+08:00'
        self.assertTrue(validate_sample({'articles':[article]},source,window))
        article['publisher']='Other'
        self.assertFalse(validate_sample({'articles':[article]},source,window))
