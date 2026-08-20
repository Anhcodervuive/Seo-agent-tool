import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from app import create_app
from app.models import Client, Ga4DailyMetric, GscDailyMetric, db
from scripts.reconcile_daily_trends import build_missing_daily_trend_plan, reconcile_missing_daily_trends


class DailyTrendReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_uri = config.SQLALCHEMY_DATABASE_URI
        config.SQLALCHEMY_DATABASE_URI = "sqlite://"
        cls.app = create_app()

    @classmethod
    def tearDownClass(cls):
        config.SQLALCHEMY_DATABASE_URI = cls.original_uri

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _client(self, name, *, ga4=True, gsc=True):
        slug = name.lower().replace(" ", "-")
        client = Client(
            name=name,
            domain=f"{slug}.example",
            ga4_property_id="123" if ga4 else None,
            gsc_site_url=f"https://{slug}.example/" if gsc else None,
        )
        db.session.add(client)
        db.session.flush()
        return client

    def test_plan_selects_only_configured_sources_without_daily_history(self):
        empty = self._client("Empty")
        existing = self._client("Existing")
        partial = self._client("Partial")
        self._client("Unconfigured", ga4=False, gsc=False)
        db.session.add_all([
            Ga4DailyMetric(client_id=existing.id, metric_date=date(2026, 8, 1), sessions=10),
            GscDailyMetric(client_id=existing.id, metric_date=date(2026, 8, 1), clicks=3),
            Ga4DailyMetric(client_id=partial.id, metric_date=date(2026, 8, 1), sessions=7),
        ])
        db.session.commit()

        plan = build_missing_daily_trend_plan()
        projects = {project["client_id"]: project for project in plan["projects"]}

        self.assertEqual(plan["scanned_projects"], 4)
        self.assertEqual(plan["eligible_projects"], 2)
        self.assertEqual(projects[empty.id]["sources"]["ga4"]["action"], "sync")
        self.assertEqual(projects[empty.id]["sources"]["gsc"]["action"], "sync")
        self.assertEqual(projects[partial.id]["sources"]["ga4"]["action"], "skip")
        self.assertEqual(projects[partial.id]["sources"]["gsc"]["action"], "sync")
        self.assertNotIn(existing.id, projects)

    @patch("scripts.reconcile_daily_trends.backfill_project_daily_trends")
    def test_dry_run_never_calls_provider_backfill(self, backfill):
        self._client("Missing")
        summary = reconcile_missing_daily_trends(dry_run=True)
        backfill.assert_not_called()
        self.assertEqual(summary["source_status_counts"], {"planned": 2})

    @patch("scripts.reconcile_daily_trends.backfill_project_daily_trends")
    def test_source_failures_are_isolated_across_sources_and_projects(self, backfill):
        first = self._client("First")
        second = self._client("Second", ga4=False, gsc=True)

        def fake_backfill(client_id, *, include_ga4, include_gsc, **_kwargs):
            if include_ga4:
                raise RuntimeError("GA4 is unavailable")
            return {
                "ga4": {"status": "not_requested", "daily_rows_written": 0},
                "gsc": {"status": "completed", "daily_rows_written": 31},
            }

        backfill.side_effect = fake_backfill
        summary = reconcile_missing_daily_trends()

        self.assertEqual(backfill.call_count, 3)
        self.assertEqual(summary["source_status_counts"], {"failed": 1, "completed": 2})
        results = {project["client_id"]: project["sources"] for project in summary["projects"]}
        self.assertEqual(results[first.id]["ga4"]["status"], "failed")
        self.assertEqual(results[first.id]["gsc"]["status"], "completed")
        self.assertEqual(results[second.id]["gsc"]["status"], "completed")

    def test_max_projects_defers_remaining_eligible_projects(self):
        self._client("First")
        self._client("Second")
        plan = build_missing_daily_trend_plan(max_projects=1)
        self.assertEqual(plan["eligible_projects"], 2)
        self.assertEqual(len(plan["projects"]), 1)
        self.assertEqual(plan["deferred_projects"], 1)


if __name__ == "__main__":
    unittest.main()
