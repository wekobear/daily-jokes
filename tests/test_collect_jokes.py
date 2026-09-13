import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_jokes import REVISION, collect, parse_issue

FIXTURE = "## 虚构测试日刊\n</hr>\n### :test: { 第1档 } 标题一\n甲说&amp;乙答。<br/><br/>结束。\n</hr>\n### :test: { 第2档 } 空内容\n<hr/>\n### :test: { 第3档 } 标题三\n另一个包袱。\n"
PATH = "joke/2018/06/28.md"


class CollectorTests(unittest.TestCase):
    def fake(self, url):
        if "api.github.com" in url:
            return json.dumps({"tree": [{"path": PATH, "type": "blob"},
                                        {"path": "run.py", "type": "blob"},
                                        {"path": "joke/2018/06/29.md", "type": "blob"}]})
        return FIXTURE

    def test_parse_and_attribution(self):
        records = parse_issue(FIXTURE, PATH)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["text"], "甲说&乙答。\n结束。")
        self.assertTrue(records[0]["source"]["url"].endswith("#L3"))
        self.assertIn(REVISION, records[0]["source"]["url"])
        self.assertEqual(records[0]["source"]["issue_date"], "2018-06-28")
        self.assertEqual(records[0]["review_status"], "unreviewed")

    def test_bad_path(self):
        with self.assertRaises(ValueError):
            parse_issue(FIXTURE, "../../private.md")

    def test_dedup_across_issues_and_shortfall(self):
        result = collect("2026-09-13", count=30, fetcher=self.fake)
        self.assertEqual(result["available_issue_files"], 2)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["shortfall"], 28)

    def test_deterministic_sampling(self):
        a = collect("2026-09-13", count=1, fetcher=self.fake)
        b = collect("2026-09-13", count=1, fetcher=self.fake)
        self.assertEqual([r["id"] for r in a["candidates"]], [r["id"] for r in b["candidates"]])

    def test_partial_failure(self):
        def broken(url):
            if url.endswith("29.md"):
                raise OSError("offline")
            return self.fake(url)
        result = collect("2026-09-13", fetcher=broken)
        self.assertEqual(len(result["failed_issues"]), 1)
        self.assertEqual(len(result["loaded_issues"]), 1)
        self.assertEqual(result["candidate_count"], 2)

    def test_no_entries(self):
        self.assertEqual(parse_issue("Not a joke issue", PATH), [])

    def test_invalid_input(self):
        for kwargs in ({"count": 0}, {"issues": 11}, {"count": 101}):
            with self.assertRaises(ValueError):
                collect("2026-09-13", fetcher=self.fake, **kwargs)
        with self.assertRaises(ValueError):
            collect("not-date", fetcher=self.fake)

    def test_truncated_tree(self):
        with self.assertRaises(ValueError):
            collect("2026-09-13", fetcher=lambda _: '{"tree": [], "truncated": true}')

    def test_punctuation_dedup(self):
        a = parse_issue("### { 第1档 } A\n甲，乙！", PATH)[0]
        b = parse_issue("### { 第1档 } B\n甲 乙", PATH)[0]
        self.assertEqual(a["fingerprint"], b["fingerprint"])


if __name__ == "__main__":
    unittest.main()
