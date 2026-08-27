import unittest

import config
from app import create_app
from app.models import Client, User, db


class OptionalGoogleProjectSettingsTests(unittest.TestCase):
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
            admin = User(username="admin", password_hash="not-used", role="admin")
            db.session.add(admin)
            db.session.commit()
            self.admin_id = admin.id

        self.http_client = self.app.test_client()
        with self.http_client.session_transaction() as session:
            session["_user_id"] = str(self.admin_id)
            session["_fresh"] = True

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_project_can_be_created_without_google_sources(self):
        response = self.http_client.post(
            "/add",
            data={"name": "No Google Project", "domain": "example.test"},
        )

        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            project = Client.query.one()
            self.assertEqual("https://example.test", project.domain)
            self.assertIsNone(project.google_account_id)
            self.assertEqual("", project.ga4_property_id)
            self.assertEqual("", project.gsc_site_url)

    def test_project_can_use_only_ga4(self):
        response = self.http_client.post(
            "/add",
            data={
                "name": "GA4 Project",
                "domain": "ga4.example.test",
                "ga4_property_id": "123456789",
            },
        )

        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            project = Client.query.one()
            self.assertEqual("123456789", project.ga4_property_id)
            self.assertEqual("", project.gsc_site_url)

    def test_project_can_use_only_gsc(self):
        response = self.http_client.post(
            "/add",
            data={
                "name": "GSC Project",
                "domain": "gsc.example.test",
                "gsc_site_url": "sc-domain:gsc.example.test",
            },
        )

        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            project = Client.query.one()
            self.assertEqual("", project.ga4_property_id)
            self.assertEqual("sc-domain:gsc.example.test", project.gsc_site_url)

    def test_edit_can_disconnect_google_sources_without_deleting_project(self):
        with self.app.app_context():
            project = Client(
                name="Connected Project",
                domain="https://connected.example.test",
                ga4_property_id="123456789",
                gsc_site_url="sc-domain:connected.example.test",
            )
            db.session.add(project)
            db.session.commit()
            project_id = project.id

        response = self.http_client.post(
            f"/project/{project_id}/edit",
            data={"name": "Connected Project", "domain": "connected.example.test"},
        )

        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            project = db.session.get(Client, project_id)
            self.assertIsNotNone(project)
            self.assertEqual("", project.ga4_property_id)
            self.assertEqual("", project.gsc_site_url)


if __name__ == "__main__":
    unittest.main()
