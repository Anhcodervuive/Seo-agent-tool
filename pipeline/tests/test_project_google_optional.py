import unittest

import config
from app import create_app
from app.models import Client, GoogleAccountConfig, User, db


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

    def add_google_account(self, *, name="Project Google", is_default=True, active=True):
        with self.app.app_context():
            account = GoogleAccountConfig(
                name=name,
                service_email="seo@example.test",
                credentials_path="google-accounts/test.json",
                is_default=is_default,
                active=active,
            )
            db.session.add(account)
            db.session.commit()
            return account.id

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

    def test_create_page_presents_google_sources_as_optional(self):
        response = self.http_client.get("/add")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Data Sources", response.data)
        self.assertIn(b"Skip for now", response.data)
        self.assertNotIn(b'name="ga4_property_id" class="form-control" placeholder="e.g. 381960609" required', response.data)
        self.assertNotIn(b'name="gsc_site_url" class="form-control" placeholder="e.g. sc-domain:acme.com" required', response.data)

    def test_project_can_use_only_ga4(self):
        account_id = self.add_google_account()
        response = self.http_client.post(
            "/add",
            data={
                "name": "GA4 Project",
                "domain": "ga4.example.test",
                "google_account_id": str(account_id),
                "ga4_property_id": "123456789",
            },
        )

        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            project = Client.query.one()
            self.assertEqual(account_id, project.google_account_id)
            self.assertEqual("123456789", project.ga4_property_id)
            self.assertEqual("", project.gsc_site_url)

    def test_project_can_use_only_gsc(self):
        account_id = self.add_google_account()
        response = self.http_client.post(
            "/add",
            data={
                "name": "GSC Project",
                "domain": "gsc.example.test",
                "google_account_id": str(account_id),
                "gsc_site_url": "sc-domain:gsc.example.test",
            },
        )

        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            project = Client.query.one()
            self.assertEqual(account_id, project.google_account_id)
            self.assertEqual("", project.ga4_property_id)
            self.assertEqual("sc-domain:gsc.example.test", project.gsc_site_url)

    def test_google_source_requires_an_active_account(self):
        response = self.http_client.post(
            "/add",
            data={"name": "Broken Mapping", "domain": "broken.example.test", "ga4_property_id": "123"},
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Choose an active Google account", response.data)
        with self.app.app_context():
            self.assertEqual(0, Client.query.count())

    def test_explicit_google_account_is_pinned_instead_of_default(self):
        self.add_google_account(name="Default")
        selected_id = self.add_google_account(name="Selected", is_default=False)
        response = self.http_client.post(
            "/add",
            data={
                "name": "Pinned Project",
                "domain": "pinned.example.test",
                "google_account_id": str(selected_id),
                "gsc_site_url": "sc-domain:pinned.example.test",
            },
        )

        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            self.assertEqual(selected_id, Client.query.one().google_account_id)

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

    def test_edit_page_uses_settings_navigation_and_connection_status(self):
        with self.app.app_context():
            project = Client(
                name="Settings Project",
                domain="https://settings.example.test",
                ga4_property_id="123456789",
            )
            db.session.add(project)
            db.session.commit()
            project_id = project.id

        response = self.http_client.get(f"/project/{project_id}/edit")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"settings-navigation", response.data)
        self.assertIn(b"Unsaved changes", response.data)
        self.assertIn(b"Account required", response.data)
        self.assertIn(b"Not connected", response.data)
        self.assertNotIn(b"Configured", response.data)
        self.assertNotIn(b"<button type=\"button\" class=\"btn btn-outline-light px-4\" data-form-prev", response.data)


if __name__ == "__main__":
    unittest.main()
