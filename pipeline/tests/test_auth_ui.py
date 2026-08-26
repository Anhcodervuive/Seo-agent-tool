import unittest

import config
from app import create_app
from app.models import User, db


class AuthenticationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_uri = config.SQLALCHEMY_DATABASE_URI
        config.SQLALCHEMY_DATABASE_URI = "sqlite://"
        cls.app = create_app()
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        config.SQLALCHEMY_DATABASE_URI = cls.original_uri

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()

            admin = User(username="admin", role="admin")
            admin.set_password("admin-password")
            member = User(username="analyst", role="team_member")
            member.set_password("member-password")
            db.session.add_all([admin, member])
            db.session.commit()

        self.http_client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self, username, password):
        return self.http_client.post(
            "/login",
            data={"username": username, "password": password},
        )

    def test_guest_login_uses_the_dedicated_accessible_auth_layout(self):
        response = self.http_client.get("/login")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Sign in | SEO Copilot", response.data)
        self.assertIn(b"app-navbar-public", response.data)
        self.assertIn(b"auth-shell", response.data)
        self.assertIn(b"auth-card", response.data)
        self.assertIn(b'data-password-toggle', response.data)
        self.assertIn(b'autocomplete="username"', response.data)
        self.assertIn(b'autocomplete="current-password"', response.data)
        self.assertNotIn(b"autofocus", response.data)
        self.assertIn(b'data-auth-submit-loading', response.data)
        self.assertNotIn(b"app-primary-nav", response.data)
        self.assertNotIn(b"bg-dark", response.data)

    def test_invalid_login_keeps_the_error_inside_the_auth_experience(self):
        response = self._login("admin", "wrong-password")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"auth-alert-error", response.data)
        self.assertIn(b"Invalid username or password", response.data)
        self.assertLess(response.data.index(b"auth-card"), response.data.index(b"Invalid username or password"))

    def test_valid_admin_login_preserves_redirect_and_renders_compact_account_menu(self):
        login_response = self._login("admin", "admin-password")

        self.assertEqual(302, login_response.status_code)
        self.assertTrue(login_response.headers["Location"].endswith("/"))

        response = self.http_client.get("/keyword-research")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"app-navbar-authenticated", response.data)
        self.assertIn(b"app-primary-nav", response.data)
        self.assertIn(b"app-account-trigger", response.data)
        self.assertIn(b"Admin settings", response.data)
        self.assertIn(b"Sign out", response.data)
        self.assertIn(b'aria-current="page"', response.data)

    def test_team_member_account_menu_does_not_expose_admin_settings(self):
        login_response = self._login("analyst", "member-password")
        self.assertEqual(302, login_response.status_code)

        response = self.http_client.get("/")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"analyst", response.data)
        self.assertIn(b"Team Member", response.data)
        self.assertIn(b"Sign out", response.data)
        self.assertNotIn(b"Admin settings", response.data)


if __name__ == "__main__":
    unittest.main()
