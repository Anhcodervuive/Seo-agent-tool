import unittest

from services.audit_status import build_audit_status_summary


class AuditStatusTests(unittest.TestCase):
    def test_partial_ranking_and_report_are_explained_independently(self):
        summary = build_audit_status_summary("partial", {
            "rankings": {
                "rows": 200,
                "failed_rows": 85,
                "errors": ["example.com / keyword: DataForSEO 50000: Internal SE Server Error"],
            },
            "stage_results": [
                {"name": "crawl", "status": "complete", "optional": False},
                {"name": "rankings", "status": "partial", "optional": True},
                {"name": "report", "status": "failed", "optional": True, "error": "HTTP 404"},
            ],
        })

        self.assertEqual("Completed with warnings", summary["label"])
        self.assertEqual(2, len(summary["issues"]))
        ranking_issue = next(issue for issue in summary["issues"] if issue["stage"] == "rankings")
        self.assertIn("85 of 200", ranking_issue["title"])
        self.assertIn("Internal SE Server Error", ranking_issue["technical_detail"])
        report_issue = next(issue for issue in summary["issues"] if issue["stage"] == "report")
        self.assertIn("AI report", report_issue["title"])

    def test_legacy_failed_report_is_not_an_unexplained_failed_badge(self):
        summary = build_audit_status_summary("failed", {
            "report": "FAILED: 404 Client Error: Not Found",
        })

        self.assertEqual("Needs attention", summary["label"])
        self.assertEqual("report", summary["issues"][0]["stage"])
        self.assertIn("404", summary["issues"][0]["technical_detail"])
