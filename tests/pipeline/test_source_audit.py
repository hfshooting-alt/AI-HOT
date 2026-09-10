import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from audit_manus_sources import audit, audit_links  # noqa: E402


class TestSourceAudit(unittest.TestCase):
    def test_valid_sources_are_counted(self):
        report = audit({"group_a": [
            {"account_name": "A", "platform": "Tencent News", "home_url": "https://a.example/x"},
            {"account_name": "B", "platform": "NetEase", "home_url": "https://b.example/y"},
        ]})
        self.assertTrue(report["ok"])
        self.assertEqual(report["configuredAccounts"], 2)
        self.assertEqual(report["groups"], {"group_a": 2})

    def test_duplicate_and_unsafe_urls_are_rejected(self):
        report = audit({
            "group_a": [{"account_name": "A", "platform": "P", "home_url": "http://u:p@x.test/"}],
            "group_b": [{"account_name": "A", "platform": "P", "home_url": "http://u:p@x.test"}],
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["duplicateNames"], ["A"])
        self.assertTrue(report["duplicateUrls"])
        self.assertTrue(any("HTTPS" in error for error in report["errors"]))
        self.assertTrue(any("认证信息" in error for error in report["errors"]))

    def test_link_audit_calls_each_source_once_and_separates_restrictions(self):
        calls = []
        def checker(url):
            calls.append(url)
            return ({"reachable": True, "restricted": True, "status": 403}
                    if "restricted" in url else
                    {"reachable": False, "restricted": False, "error": "connection_failed"})
        groups = {"group_a": [
            {"account_name": "A", "platform": "P", "home_url": "https://restricted.test/a"},
            {"account_name": "B", "platform": "P", "home_url": "https://down.test/b"},
        ]}
        report = audit_links(groups, checker=checker, concurrency=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report["requests"], 2)
        self.assertEqual(report["reachableAccounts"], 1)
        self.assertEqual(report["restrictedAccounts"], 1)
        self.assertEqual(report["unreachableAccounts"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
