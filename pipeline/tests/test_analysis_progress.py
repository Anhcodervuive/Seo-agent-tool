import json
import unittest

import config
from app import create_app
from app.models import Client, Snapshot, User, db
from services.analysis_progress import build_analysis_progress_presentation


class AnalysisProgressPresentationTests(unittest.TestCase):
    def test_background_ranking_is_visible_while_crawl_is_active(self):
        presentation = build_analysis_progress_presentation({
            "phase": "crawl",
            "workflow_total_stages": 7,
            "workflow_finished_stages": 0,
            "workflow_current_stage": "crawl",
            "workflow_current_stage_label": "Crawling website",
            "workflow_current_stage_position": 1,
            "crawled_urls": 20,
            "discovered_urls": 80,
            "pending_urls": 60,
            "ranking_state": "processing",
            "ranking_submitted": 100,
            "ranking_completed": 0,
            "ranking_pending": 100,
            "ranking_total": 100,
        }, "running")

        self.assertEqual("Stage 1 of 7 · Crawling website", presentation["workflow"]["summary"])
        self.assertEqual(3.57, presentation["workflow"]["percent"])
        self.assertEqual("100 checks processing in DataForSEO", presentation["rankings"]["label"])
        self.assertIn("after the independent audit stages", presentation["rankings"]["detail"])
        self.assertEqual("60 pending · 80 discovered", presentation["crawl"]["detail"])

    def test_ranking_collection_contributes_only_the_active_stage_fraction(self):
        presentation = build_analysis_progress_presentation({
            "phase": "rankings",
            "workflow_total_stages": 7,
            "workflow_finished_stages": 5,
            "workflow_current_stage": "rankings",
            "workflow_current_stage_label": "Checking keyword rankings",
            "workflow_current_stage_position": 6,
            "ranking_state": "collecting",
            "ranking_submitted": 100,
            "ranking_completed": 50,
            "ranking_pending": 50,
            "ranking_total": 100,
        }, "running")

        self.assertEqual("Stage 6 of 7 · Checking keyword rankings", presentation["workflow"]["summary"])
        self.assertEqual(78.57, presentation["workflow"]["percent"])
        self.assertEqual("Collecting ranking results from DataForSEO", presentation["rankings"]["label"])
        self.assertEqual("50 of 100 results collected · 50 remaining.", presentation["rankings"]["detail"])

    def test_old_live_snapshot_uses_safe_counter_fallback(self):
        presentation = build_analysis_progress_presentation({
            "phase": "crawl",
            "phase_label": "Crawling website",
            "crawled_urls": 75,
            "discovered_urls": 100,
            "pending_urls": 25,
        }, "running")

        self.assertEqual(75.0, presentation["workflow"]["percent"])
        self.assertEqual("Crawling website", presentation["workflow"]["summary"])
        self.assertEqual("Ranking checks not started", presentation["rankings"]["label"])

    def test_terminal_status_is_always_complete_for_the_progress_surface(self):
        presentation = build_analysis_progress_presentation({
            "phase": "partial",
            "workflow_total_stages": 7,
            "workflow_finished_stages": 6,
        }, "partial")

        self.assertEqual(100, presentation["workflow"]["percent"])
        self.assertEqual("All audit stages finished", presentation["workflow"]["summary"])


class AnalysisProgressRouteTests(unittest.TestCase):
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
            client = Client(name="Progress test", domain="progress.test")
            admin = User(username="progress-admin", password_hash="not-used", role="admin")
            db.session.add_all([client, admin])
            db.session.flush()
            snapshot = Snapshot(
                client_id=client.id,
                status="running",
                notes=json.dumps({"progress": {
                    "phase": "crawl",
                    "phase_label": "Crawling website",
                    "workflow_total_stages": 7,
                    "workflow_finished_stages": 0,
                    "workflow_current_stage": "crawl",
                    "workflow_current_stage_label": "Crawling website",
                    "workflow_current_stage_position": 1,
                    "crawled_urls": 20,
                    "discovered_urls": 80,
                    "pending_urls": 60,
                    "ranking_state": "processing",
                    "ranking_submitted": 100,
                    "ranking_completed": 0,
                    "ranking_pending": 100,
                    "ranking_total": 100,
                }}),
            )
            db.session.add(snapshot)
            db.session.commit()
            self.client_id = client.id
            self.snapshot_id = snapshot.id
            self.admin_id = admin.id
        self.http_client = self.app.test_client()
        with self.http_client.session_transaction() as session:
            session["_user_id"] = str(self.admin_id)
            session["_fresh"] = True

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_progress_api_and_card_render_parallel_ranking_state(self):
        api_response = self.http_client.get(
            f"/project/{self.client_id}/analysis-progress",
            query_string={"snapshot_id": self.snapshot_id},
        )
        self.assertEqual(200, api_response.status_code)
        payload = api_response.get_json()
        self.assertEqual("processing", payload["presentation"]["rankings"]["state"])
        self.assertEqual("100 checks processing in DataForSEO", payload["presentation"]["rankings"]["label"])
        self.assertEqual(3.57, payload["presentation"]["workflow"]["percent"])

        page_response = self.http_client.get(f"/project/{self.client_id}")
        self.assertEqual(200, page_response.status_code)
        self.assertIn(b"data-progress-overall", page_response.data)
        self.assertIn(b"data-progress-ranking-status", page_response.data)
        self.assertIn(b"100 checks processing in DataForSEO", page_response.data)


if __name__ == "__main__":
    unittest.main()
