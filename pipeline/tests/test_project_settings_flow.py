import unittest

import config
from app import create_app
from app.models import Client, Competitor, Keyword, User, db


class ProjectSettingsFlowTests(unittest.TestCase):
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
            self.project = Client(
                name="Existing Project",
                domain="https://existing.example",
                location="United Kingdom",
                ga4_property_id="111",
                gsc_site_url="sc-domain:existing.example",
            )
            self.admin = User(username="admin", password_hash="not-used", role="admin")
            db.session.add_all([self.project, self.admin])
            db.session.flush()
            db.session.add_all([
                Keyword(
                    client_id=self.project.id,
                    keyword="old keyword",
                    location="United Kingdom",
                    language="en",
                    device="desktop",
                    priority="medium",
                ),
                Competitor(client_id=self.project.id, domain="https://old-competitor.example"),
            ])
            db.session.commit()
            self.project_id = self.project.id
            self.admin_id = self.admin.id

        self.http_client = self.app.test_client()
        with self.http_client.session_transaction() as session:
            session["_user_id"] = str(self.admin_id)
            session["_fresh"] = True

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_edit_project_ui_uses_settings_shell_without_changing_post_contract(self):
        page = self.http_client.get(f"/project/{self.project_id}/edit")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'project-settings-form', page.data)
        self.assertIn(b'Batch add keywords', page.data)
        self.assertIn(b'Review &amp; edit tracked keywords', page.data)
        self.assertIn(b'data-bulk-keywords-language', page.data)
        self.assertIn(b'Vietnamese', page.data)
        self.assertIn(b'data-form-tab="schedule"', page.data)
        self.assertIn(b'name="full_audit_schedule_enabled"', page.data)
        self.assertIn(b'name="rank_check_schedule_enabled"', page.data)

        response = self.http_client.post(
            f"/project/{self.project_id}/edit",
            data={
                "name": "Updated Project",
                "domain": "updated.example",
                "location": "United Kingdom",
                "competitor_traffic_locations": ["United States"],
                "business_context": "A local service business.",
                "ga4_property_id": "222",
                "gsc_site_url": "sc-domain:updated.example",
                "crawl_mode": "path",
                "crawl_paths": "/services\n/blog",
                "keywords": "new primary|high|mobile|United Kingdom|vi\nnew secondary|low|desktop|United Kingdom|en",
                "competitors": "competitor-one.example, https://competitor-two.example",
                "ai_model_override": "",
                "ai_prompt_override": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/project/{self.project_id}".encode(), response.headers["Location"].encode())

        with self.app.app_context():
            project = db.session.get(Client, self.project_id)
            self.assertEqual(project.name, "Updated Project")
            self.assertEqual(project.domain, "https://updated.example")
            self.assertEqual(project.location, "United Kingdom")
            self.assertEqual(project.competitor_traffic_locations, ["United States"])
            self.assertEqual(project.ga4_property_id, "222")
            self.assertEqual(project.gsc_site_url, "sc-domain:updated.example")
            self.assertEqual(project.crawl_mode, "path")
            self.assertEqual(project.crawl_paths, "/services\n/blog")
            keywords = Keyword.query.filter_by(client_id=self.project_id).order_by(Keyword.keyword.asc()).all()
            self.assertEqual([keyword.keyword for keyword in keywords], ["new primary", "new secondary"])
            self.assertEqual(keywords[0].priority, "high")
            self.assertEqual(keywords[0].device, "mobile")
            self.assertEqual(keywords[0].location, "United Kingdom")
            self.assertEqual(keywords[0].language, "vi")
            self.assertEqual(keywords[1].priority, "low")
            competitors = Competitor.query.filter_by(client_id=self.project_id).order_by(Competitor.domain.asc()).all()
            self.assertEqual(
                [competitor.domain for competitor in competitors],
                ["https://competitor-one.example", "https://competitor-two.example"],
            )

    def test_create_project_preserves_keyword_and_competitor_payload_format(self):
        page = self.http_client.get("/add")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'form="project-settings-form"', page.data)
        self.assertIn(b'Batch add keywords', page.data)
        self.assertIn(b'data-keyword-field="language"', page.data)
        self.assertIn(b'Schedules become available after creation', page.data)

        response = self.http_client.post(
            "/add",
            data={
                "name": "Created Project",
                "domain": "created.example",
                "location": "United Kingdom",
                "business_context": "Created through the current project form.",
                "ga4_property_id": "333",
                "gsc_site_url": "sc-domain:created.example",
                "crawl_mode": "full",
                "crawl_paths": "",
                "keywords": "created keyword|medium|desktop|United Kingdom|en",
                "competitors": "created-competitor.example",
                "ai_model_override": "",
                "ai_prompt_override": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            project = Client.query.filter_by(name="Created Project").one()
            self.assertEqual(project.domain, "https://created.example")
            self.assertEqual(Keyword.query.filter_by(client_id=project.id).one().keyword, "created keyword")
            self.assertEqual(Competitor.query.filter_by(client_id=project.id).one().domain, "https://created-competitor.example")

    def test_unsupported_keyword_language_is_rejected_before_existing_rows_are_replaced(self):
        response = self.http_client.post(
            f"/project/{self.project_id}/edit",
            data={
                "name": "Existing Project",
                "domain": "https://existing.example",
                "location": "United Kingdom",
                "ga4_property_id": "111",
                "gsc_site_url": "sc-domain:existing.example",
                "keywords": "replacement|medium|desktop|United Kingdom|xx",
                "competitors": "https://old-competitor.example",
            },
        )
        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            keywords = Keyword.query.filter_by(client_id=self.project_id).all()
            self.assertEqual(["old keyword"], [keyword.keyword for keyword in keywords])


if __name__ == "__main__":
    unittest.main()
