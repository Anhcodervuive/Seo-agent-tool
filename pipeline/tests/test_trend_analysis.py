import datetime
import unittest
from types import SimpleNamespace

import config
from app import create_app
from app.models import BacklinkHistory, Client, CrawlIssue, CrawlPage, Ga4DailyMetric, GscDailyMetric, Snapshot, User, db
from scripts.backfill_daily_trends import daily_trend_ranges
from services.trend_analysis import _latest_snapshot_point_per_day, _summary, get_project_trends


class TrendSummaryTests(unittest.TestCase):
    def test_summary_reports_positive_change(self):
        summary = _summary([{"value": 100}, {"value": 125}])
        self.assertEqual(125, summary["latest"])
        self.assertEqual(25, summary["absolute_change"])
        self.assertEqual(25.0, summary["percent_change"])
        self.assertEqual("up", summary["health_direction"])

    def test_issue_reduction_is_positive_for_project_health(self):
        summary = _summary([{"value": 700}, {"value": 500}], inverse_health=True)
        self.assertEqual("down", summary["direction"])
        self.assertEqual("up", summary["health_direction"])

    def test_zero_baseline_has_no_infinite_percentage(self):
        summary = _summary([{"value": 0}, {"value": 10}])
        self.assertIsNone(summary["percent_change"])

    def test_empty_series_has_stable_shape(self):
        summary = _summary([])
        self.assertIsNone(summary["latest"])
        self.assertEqual(0, summary["data_points"])

    def test_same_day_audits_keep_the_latest_observation(self):
        snapshots = [
            SimpleNamespace(id=10, created_at=datetime.datetime(2026, 8, 19, 9, 0)),
            SimpleNamespace(id=11, created_at=datetime.datetime(2026, 8, 19, 15, 0)),
        ]
        points = _latest_snapshot_point_per_day(snapshots, {10: 700, 11: 500})
        self.assertEqual([{"date": "2026-08-19", "value": 500, "snapshot_id": 11}], points)

    def test_backfill_ranges_cover_the_longest_90_day_yoy_window(self):
        today = datetime.date(2026, 8, 19)
        ranges = daily_trend_ranges(455, today=today)
        self.assertEqual(today, ranges["ga4"][1])
        self.assertEqual(today - datetime.timedelta(days=454), ranges["ga4"][0])
        self.assertEqual(today - datetime.timedelta(days=3), ranges["gsc"][1])


class TrendComparisonServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_uri = config.SQLALCHEMY_DATABASE_URI
        config.SQLALCHEMY_DATABASE_URI = "sqlite://"
        cls.app = create_app()

    @classmethod
    def tearDownClass(cls):
        config.SQLALCHEMY_DATABASE_URI = cls.original_uri

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            client = Client(name="Trend test", domain="trend.test")
            admin = User(username="trend-admin", password_hash="not-used", role="admin")
            db.session.add_all([client, admin])
            db.session.commit()
            self.client_id = client.id
            self.admin_id = admin.id
        self.http_client = self.app.test_client()
        with self.http_client.session_transaction() as session:
            session["_user_id"] = str(self.admin_id)
            session["_fresh"] = True

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _add_daily_window(self, end_date, *, sessions, clicks, impressions, days=30):
        for offset in range(days):
            metric_date = end_date - datetime.timedelta(days=offset)
            db.session.add(Ga4DailyMetric(
                client_id=self.client_id,
                metric_date=metric_date,
                sessions=sessions,
                total_users=sessions / 2,
            ))
            db.session.add(GscDailyMetric(
                client_id=self.client_id,
                metric_date=metric_date,
                clicks=clicks,
                impressions=impressions,
                ctr=clicks / impressions if impressions else 0,
            ))

    def _add_audit_observation(self, observed_on, *, issue_count, backlinks, referring_domains):
        snapshot = Snapshot(
            client_id=self.client_id,
            status="complete",
            created_at=datetime.datetime.combine(observed_on, datetime.time(hour=12)),
        )
        db.session.add(snapshot)
        db.session.flush()
        db.session.add(CrawlPage(snapshot_id=snapshot.id, url=f"https://trend.test/{snapshot.id}"))
        for index in range(issue_count):
            db.session.add(CrawlIssue(
                snapshot_id=snapshot.id,
                issue=f"Issue {index}",
                issue_type="warning",
            ))
        db.session.add(BacklinkHistory(
            snapshot_id=snapshot.id,
            total_backlinks=backlinks,
            referring_domains=referring_domains,
        ))

    def test_equal_windows_and_yoy_use_aggregates_and_weighted_ctr(self):
        end_date = datetime.date(2026, 8, 19)
        previous_end = end_date - datetime.timedelta(days=30)
        year_end = end_date.replace(year=2025)
        with self.app.app_context():
            self._add_daily_window(end_date, sessions=20, clicks=20, impressions=200)
            self._add_daily_window(previous_end, sessions=10, clicks=5, impressions=100)
            self._add_daily_window(year_end, sessions=5, clicks=4, impressions=100)
            self._add_audit_observation(end_date, issue_count=5, backlinks=120, referring_domains=60)
            self._add_audit_observation(previous_end, issue_count=10, backlinks=100, referring_domains=50)
            self._add_audit_observation(year_end, issue_count=20, backlinks=80, referring_domains=40)
            db.session.commit()

            payload = get_project_trends(self.client_id, 30, end_date=end_date)

        ga4 = payload["summary"]["ga4_sessions"]
        ga4_period = ga4["comparison"]["period_over_period"]
        ga4_yoy = ga4["comparison"]["year_over_year"]
        self.assertEqual(600, ga4["latest"])
        self.assertTrue(ga4_period["available"])
        self.assertEqual(300, ga4_period["baseline"]["value"])
        self.assertEqual(100.0, ga4_period["percent_change"])
        self.assertTrue(ga4_yoy["available"])
        self.assertEqual(300.0, ga4_yoy["percent_change"])

        ctr = payload["summary"]["gsc_ctr"]
        self.assertEqual(10.0, ctr["latest"])
        self.assertEqual(5.0, ctr["comparison"]["period_over_period"]["baseline"]["value"])
        self.assertEqual(100.0, ctr["comparison"]["period_over_period"]["percent_change"])
        self.assertEqual(30, len(payload["series"]["ga4_sessions"]))

        crawl = payload["summary"]["crawl_issues"]["comparison"]["period_over_period"]
        self.assertTrue(crawl["available"])
        self.assertEqual(-5, crawl["absolute_change"])
        self.assertEqual("up", crawl["health_direction"])
        backlinks = payload["summary"]["backlinks"]["comparison"]["period_over_period"]
        self.assertEqual(20.0, backlinks["percent_change"])

    def test_daily_comparison_needs_coverage_in_both_windows(self):
        end_date = datetime.date(2026, 8, 19)
        previous_end = end_date - datetime.timedelta(days=30)
        with self.app.app_context():
            self._add_daily_window(end_date, sessions=20, clicks=20, impressions=200, days=10)
            self._add_daily_window(previous_end, sessions=10, clicks=10, impressions=100)
            db.session.commit()
            payload = get_project_trends(self.client_id, 30, end_date=end_date)

        period = payload["summary"]["ga4_sessions"]["comparison"]["period_over_period"]
        self.assertFalse(period["available"])
        self.assertIn("70%", period["reason"])

    def test_gsc_uses_latest_available_date_as_the_comparison_anchor(self):
        requested_end = datetime.date(2026, 8, 19)
        available_end = requested_end - datetime.timedelta(days=3)
        previous_end = available_end - datetime.timedelta(days=30)
        year_end = available_end.replace(year=2025)
        with self.app.app_context():
            self._add_daily_window(available_end, sessions=20, clicks=20, impressions=200)
            self._add_daily_window(previous_end, sessions=10, clicks=10, impressions=100)
            self._add_daily_window(year_end, sessions=8, clicks=8, impressions=100)
            db.session.commit()
            payload = get_project_trends(self.client_id, 30, end_date=requested_end)

        gsc = payload["summary"]["gsc_clicks"]
        self.assertEqual(available_end.isoformat(), gsc["anchor_date"])
        self.assertTrue(gsc["comparison"]["period_over_period"]["available"])
        self.assertEqual(30, len(payload["series"]["gsc_clicks"]))
        self.assertEqual(
            (available_end - datetime.timedelta(days=29)).isoformat(),
            payload["series"]["gsc_clicks"][0]["date"],
        )

    def test_trend_route_and_template_expose_the_comparison_dashboard(self):
        response = self.http_client.get(f"/project/{self.client_id}?tab=trends")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"project-trends.js", response.data)
        self.assertIn(b"data-trend-detail", response.data)

        api_response = self.http_client.get(f"/project/{self.client_id}/trends/data?days=30")
        self.assertEqual(200, api_response.status_code)
        payload = api_response.get_json()
        self.assertIn("comparison", payload["summary"]["ga4_sessions"])


if __name__ == "__main__":
    unittest.main()
