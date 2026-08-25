import unittest
from types import SimpleNamespace

import config
from app import create_app
from app.models import Client, CrawlPageLink, Snapshot, User, db
from app.routes.main import _build_broken_link_report


def link(**overrides):
    values = {
        "target_url": "https://target.test/missing",
        "target_final_url": None,
        "source_url": "https://source.test/page",
        "anchor_text": "Broken",
        "is_internal": False,
        "target_status": 404,
        "target_status_source": "validator",
        "target_error_type": None,
        "target_error_message": None,
        "target_checked_at": "2026-08-25T00:00:00+00:00",
        "target_response_time_ms": 20,
        "target_redirect_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class BrokenLinkReportUnitTests(unittest.TestCase):
    def test_report_includes_network_failures_and_paginates_without_truncating_total(self):
        rows = [link(target_url=f"https://target.test/{index}") for index in range(55)]
        rows.extend([
            link(target_url="https://target.test/timeout", target_status=0, target_error_type="timeout"),
            link(target_url="https://target.test/ok", target_status=200),
            link(target_url="http://127.0.0.1", target_status=None, target_status_source="skipped", target_error_type="unsafe_target"),
        ])

        first = _build_broken_link_report(rows)
        second = _build_broken_link_report(rows, page=2)
        all_rows = _build_broken_link_report(rows, per_page=None)

        self.assertEqual(56, first["total"])
        self.assertEqual(50, len(first["rows"]))
        self.assertEqual(6, len(second["rows"]))
        self.assertEqual(56, len(all_rows["rows"]))
        self.assertEqual("Timeout", first["rows"][0]["status_label"])
        self.assertEqual(1, first["unreachable"])
        self.assertEqual(55, first["http_errors"])


class BrokenLinkReportRouteTests(unittest.TestCase):
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
            client = Client(name="Links", domain="https://links.test")
            admin = User(username="links-admin", password_hash="unused", role="admin")
            db.session.add_all([client, admin])
            db.session.flush()
            snapshot = Snapshot(client_id=client.id, status="complete")
            db.session.add(snapshot)
            db.session.flush()
            db.session.add_all([
                CrawlPageLink(
                    snapshot_id=snapshot.id,
                    source_url="https://links.test/source",
                    target_url="https://outside.test/missing",
                    target_status=404,
                    target_status_source="validator",
                ),
                CrawlPageLink(
                    snapshot_id=snapshot.id,
                    source_url="https://links.test/source",
                    target_url="https://outside.test/timeout",
                    target_status=0,
                    target_status_source="validator",
                    target_error_type="timeout",
                    target_error_message="Request timed out",
                ),
                CrawlPageLink(
                    snapshot_id=snapshot.id,
                    source_url="https://links.test/source",
                    target_url="https://outside.test/ok",
                    target_status=200,
                ),
            ])
            db.session.commit()
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

    def test_detail_and_csv_expose_http_and_network_failures_only(self):
        page = self.http_client.get(f"/snapshot/{self.snapshot_id}?tab=links")
        self.assertEqual(200, page.status_code)
        self.assertIn(b"404 Not Found", page.data)
        self.assertIn(b"Timeout", page.data)
        self.assertNotIn(b"outside.test/ok", page.data)

        csv_response = self.http_client.get(f"/snapshot/{self.snapshot_id}/broken-links/download")
        self.assertEqual(200, csv_response.status_code)
        self.assertIn("text/csv", csv_response.content_type)
        self.assertIn(b"outside.test/missing", csv_response.data)
        self.assertIn(b"outside.test/timeout", csv_response.data)
        self.assertNotIn(b"outside.test/ok", csv_response.data)


if __name__ == "__main__":
    unittest.main()
