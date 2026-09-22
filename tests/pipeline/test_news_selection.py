"""The public library and investment selection have independent membership."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from news_selection import build_public_article_library


class PublicArticleLibrary(unittest.TestCase):
    def setUp(self):
        self.row = {'id': 'aihot:one', 'title': '具体 AI 事件', 'url': 'https://example.com/one',
            'publishedAt': '2026-09-22T08:00:00+08:00', 'collector': 'aihot', 'mpName': '来源',
            'source': {'name': '来源', 'url': 'https://example.com', 'private': 'not public'},
            'summary': '上游摘要', 'selected': True, 'content_text': 'PRIVATE_BODY',
            'diagnostic': {'error': 'PRIVATE_ERROR'}, 'note': 'PRIVATE_NOTE',
            'classification': {'category': 'release'},
            'sourceRefs': [{'collector': 'aihot', 'source': '来源', 'url': 'https://example.com/one',
                            'publishedAt': '2026-09-22T08:00:00+08:00', 'body': 'PRIVATE_REF'}]}
        self.approved = {**self.row, 'summary': '人工审校后的摘要', 'summaryOrigin': 'editorial_review',
            'classification': {'category': 'general', 'tags': {'industry': 'ai'},
                'autoFallback': False, 'autoFilled': [], 'raw': 'PRIVATE_CLASSIFICATION'},
            'classificationOrigin': 'editorial_review',
            'editorialReview': {'at': '2026-09-22T18:00:00+08:00', 'reason': '回核原文', 'body': 'PRIVATE_REVIEW'},
            'garenaSelection': {'status': 'selected', 'reason': '已有投资审校理由'}}

    def test_upstream_selection_never_selects_or_classifies_an_article(self):
        for decision in (True, False):
            with self.subTest(upstream=decision):
                row = {**self.row, 'selected': decision}
                actual = build_public_article_library([row], [], {
                    row['id']: {'status': 'complete', 'relevant': False, 'reason': '普通游戏评论'}})[0]
                self.assertEqual(actual['garenaSelection'], {'status': 'not_selected', 'reason': '普通游戏评论'})
                self.assertEqual(actual['summary'], '上游摘要')
                self.assertEqual(actual['summaryOrigin'], 'upstream')
                self.assertNotIn('selected', actual)
                self.assertNotIn('classification', actual)

    def test_reviewed_summary_and_classification_override_safe_metadata(self):
        original = copy.deepcopy([self.row, self.approved])
        actual = build_public_article_library([self.row], [self.approved])[0]
        self.assertEqual(actual['summary'], '人工审校后的摘要')
        self.assertEqual(actual['summaryOrigin'], 'editorial_review')
        self.assertEqual(actual['classification']['category'], 'general')
        self.assertEqual(actual['editorialReview'], {'at': '2026-09-22T18:00:00+08:00', 'reason': '回核原文'})
        self.assertEqual(actual['garenaSelection']['reason'], '已有投资审校理由')
        self.assertNotIn('PRIVATE_', repr(actual))
        actual['classification']['tags']['industry'] = 'changed'
        actual['sourceRefs'][0]['source'] = 'changed'
        self.assertEqual([self.row, self.approved], original)

    def test_relevance_reason_is_used_when_no_prior_review_reason(self):
        approved = {k: v for k, v in self.approved.items() if k != 'garenaSelection'}
        actual = build_public_article_library([self.row], [approved], {
            self.row['id']: {'status': 'complete', 'relevant': True, 'reason': '  AI 模型\n正式发布  '}})[0]
        self.assertEqual(actual['garenaSelection'], {'status': 'selected', 'reason': 'AI 模型 正式发布'})

    def test_unknown_or_failed_results_remain_pending_without_private_error(self):
        for result in ({}, {'status': 'failed', 'reason': 'PRIVATE_FAILURE', 'error': {'message': 'PRIVATE_ERROR'}},
                       {'status': 'complete', 'relevant': True, 'reason': 'AI 事件'}):
            with self.subTest(result=result):
                actual = build_public_article_library([self.row], [], {self.row['id']: result})[0]
                self.assertEqual(actual['garenaSelection']['status'], 'pending')
                self.assertNotIn('PRIVATE_', repr(actual))

    def test_unprocessed_manus_never_borrows_summary_or_classification(self):
        row = {**self.row, 'collector': 'manus', 'metadataOnly': True}
        actual = build_public_article_library([row], [])[0]
        self.assertEqual(actual['summary'], '')
        self.assertTrue(actual['metadataOnly'])
        self.assertEqual(actual['garenaSelection']['status'], 'pending')
        self.assertNotIn('classification', actual)
        self.assertNotIn('summaryOrigin', actual)
        with self.assertRaisesRegex(ValueError, 'Metadata-only'):
            build_public_article_library([row], [self.approved])

    def test_invalid_selected_evidence_or_membership_is_rejected(self):
        variants = [[], [self.row, self.row]]
        for pool in variants:
            with self.assertRaisesRegex(ValueError, 'unique'):
                build_public_article_library(pool, [self.approved])
        for update in ({'summary': ''}, {'summary': {'body': 'PRIVATE_BODY'}}, {'classification': {}},
                       {'classification': {'category': 'general', 'autoFallback': True}}):
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, 'summary/classification'):
                build_public_article_library([self.row], [{**self.approved, **update}])


if __name__ == '__main__':
    unittest.main()
