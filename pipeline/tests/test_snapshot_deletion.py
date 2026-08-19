import unittest

from app.models import (
    BacklinkHistory,
    CrawlIssue,
    CrawlPage,
    CrawlPageImage,
    CrawlPageLink,
    CrawlPageStructuredData,
    Ga4Metric,
    GscMetric,
    Ranking,
    Snapshot,
)


class SnapshotDeletionTests(unittest.TestCase):
    def test_snapshot_relationships_delegate_cleanup_to_database(self):
        relationship_names = (
            "crawl_issues",
            "crawl_pages",
            "crawl_page_links",
            "crawl_page_images",
            "crawl_page_structured_data",
            "ga4_metrics",
            "gsc_metrics",
            "rankings",
            "backlink_history",
            "backlink_items",
            "backlink_referring_domains",
            "backlink_anchors",
            "competitor_insights",
            "competitor_country_traffic",
            "audit_job",
        )

        for relationship_name in relationship_names:
            with self.subTest(relationship=relationship_name):
                relationship = Snapshot.__mapper__.relationships[relationship_name]
                self.assertTrue(relationship.passive_deletes)

    def test_high_volume_snapshot_foreign_keys_cascade_in_database(self):
        models = (
            CrawlIssue,
            CrawlPage,
            CrawlPageLink,
            CrawlPageImage,
            CrawlPageStructuredData,
            Ga4Metric,
            GscMetric,
            Ranking,
            BacklinkHistory,
        )

        for model in models:
            with self.subTest(model=model.__name__):
                foreign_key = next(iter(model.__table__.c.snapshot_id.foreign_keys))
                self.assertEqual("CASCADE", foreign_key.ondelete)


if __name__ == "__main__":
    unittest.main()
