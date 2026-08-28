import unittest
from unittest.mock import MagicMock, patch

import config
from app import create_app
from app.models import OnePageAudit, User, db
from services.one_page_runner import _PageParser, _build_report, _run_audit


SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Swahili Beach Resort - 5 Star Resorts and Hotels Kenya</title>
    <meta name="description" content="Experience unmatched luxury at Swahili Beach Resort, the leading 5-star hotel in Diani Beach, Kenya. Book your coastal vacation today.">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="https://www.swahilibeach.com/">
    <meta property="og:title" content="Swahili Beach Resort Kenya">
    <meta property="og:description" content="5-Star luxury resort in Diani Beach.">
    <meta property="og:image" content="https://www.swahilibeach.com/images/hero.jpg">
    <meta name="twitter:card" content="summary_large_image">
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Hotel",
        "name": "Swahili Beach Resort",
        "url": "https://www.swahilibeach.com/"
    }
    </script>
</head>
<body>
    <header>
        <a href="/">Home</a>
        <a href="/rooms">Rooms & Suites</a>
        <a href="/dining">Dining</a>
        <a href="https://instagram.com/swahilibeach" rel="external">Instagram</a>
    </header>
    <main>
        <h1>Welcome to Swahili Beach Resort Kenya</h1>
        <h2>Luxury Rooms & Suites</h2>
        <p>Swahili Beach is a world-class beach hotel offering five-star amenities, cascading swimming pools, and exquisite coastal dining in Kenya.</p>
        <img src="/images/resort-pool.jpg" alt="Cascading swimming pools at Swahili Beach">
        <img src="/images/dining-view.jpg" alt="">
    </main>
</body>
</html>
"""


class OnePageAuditTests(unittest.TestCase):
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
            user = User(username="admin", password_hash="test", role="admin")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_page_parser_extracts_all_actual_elements(self):
        parser = _PageParser()
        parser.feed(SAMPLE_HTML)

        self.assertEqual("Swahili Beach Resort - 5 Star Resorts and Hotels Kenya", parser.title)
        self.assertIn("leading 5-star hotel in Diani Beach", parser.meta.get("description", ""))
        self.assertEqual("index, follow", parser.meta.get("robots"))
        self.assertEqual("https://www.swahilibeach.com/", parser.canonical)
        self.assertEqual(["Welcome to Swahili Beach Resort Kenya"], parser.headings["h1"])
        self.assertEqual(["Luxury Rooms & Suites"], parser.headings["h2"])
        self.assertEqual(2, len(parser.images))
        self.assertEqual("Cascading swimming pools at Swahili Beach", parser.images[0]["alt"])
        self.assertTrue(parser.images[0]["has_alt"])
        self.assertEqual("", parser.images[1]["alt"])
        self.assertFalse(parser.images[1]["has_alt"])
        self.assertIn("Hotel", parser.schema_types)
        self.assertEqual("Swahili Beach Resort Kenya", parser.og_tags.get("og:title"))
        self.assertEqual("https://www.swahilibeach.com/images/hero.jpg", parser.og_tags.get("og:image"))

    def test_run_audit_populates_actual_values_without_contradictions(self):
        with self.app.app_context():
            audit = OnePageAudit(
                url="https://www.swahilibeach.com/",
                normalized_url="https://www.swahilibeach.com",
                target_keyword="Swahili Beach",
                created_by_user_id=self.user_id,
                status="pending",
            )
            db.session.add(audit)
            db.session.commit()
            audit_id = audit.id

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://www.swahilibeach.com/"
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.text = SAMPLE_HTML

        with patch("requests.get", return_value=mock_resp):
            _run_audit(self.app, audit_id)

        with self.app.app_context():
            completed_audit = db.session.get(OnePageAudit, audit_id)
            self.assertEqual("complete", completed_audit.status)
            self.assertIsNotNone(completed_audit.page_data)

            seo_elements = completed_audit.page_data.get("seo_elements", {})
            self.assertEqual("Swahili Beach Resort - 5 Star Resorts and Hotels Kenya", seo_elements["title"]["value"])
            self.assertEqual(54, seo_elements["title"]["length"])
            self.assertEqual("pass", seo_elements["title"]["status"])

            # Verify no contradictory findings
            title_finding = next(f for f in completed_audit.findings if f.finding_key == "title_tag")
            self.assertEqual("pass", title_finding.status)
            self.assertIn("Swahili Beach Resort - 5 Star Resorts and Hotels Kenya", title_finding.details)
            self.assertNotIn("No title tag was found", title_finding.details)

            # Check H1 finding
            h1_finding = next(f for f in completed_audit.findings if f.finding_key == "h1_heading")
            self.assertEqual("pass", h1_finding.status)
            self.assertIn("Welcome to Swahili Beach Resort Kenya", h1_finding.details)
            self.assertNotIn("No H1 heading found", h1_finding.details)

            # Check keyword analysis
            kw_finding = next((f for f in completed_audit.findings if f.finding_key == "target_keyword_usage"), None)
            self.assertIsNotNone(kw_finding)
            self.assertEqual("pass", kw_finding.status)
            self.assertIn("Swahili Beach", kw_finding.details)


if __name__ == "__main__":
    unittest.main()
