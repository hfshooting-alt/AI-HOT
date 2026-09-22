import os
import unittest
from unittest.mock import patch
from datetime import timedelta
from manus_source.window import ten_am_window, latest_cutoff_date, timestamp, matching_item
from manus_source.checkpoints import checkpoint_articles

class RollingNewsWindow(unittest.TestCase):
    def test_seconds_and_utc_conversion(self):
        with patch.dict(os.environ, {'NEWS_COLLECTION_END': '2026-09-22T09:46:27Z'}):
            w = ten_am_window('2026-09-22')
            self.assertEqual(w['end'], '2026-09-22T17:46:27+08:00')
            self.assertEqual(timestamp(w['end']) - timestamp(w['start']), timedelta(days=1))
            self.assertEqual(latest_cutoff_date(), '2026-09-22')
            with self.assertRaises(ValueError):
                ten_am_window('2026-09-21')
    def test_naive_anchor_is_invalid(self):
        with patch.dict(os.environ, {'NEWS_COLLECTION_END': '2026-09-22T17:46:27'}):
            with self.assertRaises(ValueError):
                ten_am_window('2026-09-22')
    def test_yesterday_exception_precedes_rolling_start(self):
        with patch.dict(os.environ, {'NEWS_COLLECTION_END': '2026-09-22T17:46:27+08:00'}):
            w = ten_am_window('2026-09-22')
            self.assertTrue(matching_item(w, {'publishedAt': '2026-09-21', 'publishedPrecision': 'date',
                'timeEvidence': {'originalText': '昨天', 'observedAt': '2026-09-22T18:00:00+08:00'}}))
    def test_new_and_legacy_checkpoint_markers(self):
        response = {'messages': [{'type':'assistant_message', 'assistant_message': {
            'content': 'NEWS_ARTICLE {"title":"new"} AIHOT_ARTICLE {"title":"legacy"}'}}]}
        self.assertEqual([a['title'] for a in checkpoint_articles(response)], ['new', 'legacy'])
