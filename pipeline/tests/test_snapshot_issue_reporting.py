import unittest
from types import SimpleNamespace

from app.routes.main import _build_image_report, _build_issue_category_groups


class SnapshotIssueReportingTests(unittest.TestCase):
    def test_issue_rows_include_a_plain_language_recommended_fix(self):
        raw_issue = SimpleNamespace(
            url="https://example.com/about",
            issue="Missing meta title",
            issue_type="warning",
            details="",
        )

        groups = _build_issue_category_groups([], [], [], [], [raw_issue])
        category = next(group for group in groups if group["slug"] == "meta-titles")
        item = next(item for item in category["items"] if item["key"] == "meta_title_missing")

        self.assertEqual(1, item["count"])
        self.assertIn("unique, descriptive title", item["recommendation"])

    def test_images_report_paginates_all_rows_without_a_silent_limit(self):
        images = [
            SimpleNamespace(
                page_url="https://example.com/page",
                image_url=f"https://cdn.example.com/image-{index:03d}.jpg",
                position=index,
                alt_text="Product image",
                file_size_bytes=None,
                width=None,
                height=None,
            )
            for index in range(151)
        ]

        report = _build_image_report(images, page=2, per_page=50)

        self.assertEqual(151, report["total"])
        self.assertEqual(151, report["filtered_total"])
        self.assertEqual(4, report["total_pages"])
        self.assertEqual(2, report["current_page"])
        self.assertEqual(50, len(report["rows"]))
        self.assertTrue(report["has_previous"])
        self.assertTrue(report["has_next"])

    def test_images_report_filters_missing_alt_text(self):
        images = [
            SimpleNamespace(
                page_url="https://example.com/page-a",
                image_url="https://cdn.example.com/a.jpg",
                position=1,
                alt_text="",
                file_size_bytes=None,
                width=None,
                height=None,
            ),
            SimpleNamespace(
                page_url="https://example.com/page-b",
                image_url="https://cdn.example.com/b.jpg",
                position=1,
                alt_text="Product photo",
                file_size_bytes=None,
                width=None,
                height=None,
            ),
        ]

        report = _build_image_report(images, alt_filter="missing")

        self.assertEqual(1, report["filtered_total"])
        self.assertEqual("Missing", report["rows"][0]["alt_state"])


if __name__ == "__main__":
    unittest.main()
