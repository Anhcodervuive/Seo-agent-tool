import unittest
from unittest.mock import patch

import config
from app import create_app
from app.models import Client, Keyword, KeywordResearchResult, KeywordResearchRun, User, db
from services import dataforseo
from services.keyword_research import (
    MAX_BULK_KEYWORDS,
    claim_next_keyword_research_run,
    parse_input_keywords,
    run_keyword_research,
)


def _response(items, cost=0.01):
    return {"tasks": [{"status_code": 20000, "cost": cost, "result": [{"items": items}]}]}


class DataForSEOKeywordResearchTests(unittest.TestCase):
    def test_discovery_merges_sources_and_keeps_optional_source_error(self):
        def fake_post(url, body, timeout=120):
            if url == dataforseo.LABS_KEYWORD_IDEAS_URL:
                return _response([{
                    "keyword_data": {
                        "keyword": "seo audit checklist",
                        "keyword_info": {"search_volume": 90, "cpc": 1.25, "competition": 0.4},
                        "search_intent_info": {"main_intent": "informational"},
                    },
                    "keyword_difficulty": 42,
                }])
            if url == dataforseo.LABS_KEYWORD_SUGGESTIONS_URL:
                return _response([{
                    "keyword": "seo audit checklist",
                    "keyword_info": {"search_volume": 80},
                }, {
                    "keyword": "free seo audit",
                    "keyword_info": {"search_volume": 120},
                }])
            if url == dataforseo.SERP_ORGANIC_LIVE_ADVANCED_URL:
                return _response([{
                    "type": "people_also_ask",
                    "items": [{"title": "What is included in an SEO audit?", "url": "https://example.test/question"}],
                }])
            if url == dataforseo.SERP_AUTOCOMPLETE_LIVE_ADVANCED_URL:
                raise dataforseo.DataForSEOError("Autocomplete is temporarily unavailable.", endpoint="/autocomplete", retryable=True)
            self.fail(f"Unexpected endpoint: {url}")

        with patch.object(dataforseo, "_post", side_effect=fake_post):
            result = dataforseo.get_keyword_research_discovery("seo audit", "United Kingdom", "en", limit=100)

        rows = {row["keyword"]: row for row in result["keywords"]}
        self.assertEqual(set(rows), {"seo audit checklist", "free seo audit"})
        self.assertEqual(rows["seo audit checklist"]["source_types"], ["related", "suggestion"])
        self.assertEqual(rows["seo audit checklist"]["keyword_difficulty"], 42)
        self.assertEqual(result["questions"][0]["keyword"], "What is included in an SEO audit?")
        self.assertIn("autocomplete", result["errors"])
        self.assertTrue(result["errors"]["autocomplete"]["retryable"])

    def test_metric_batch_maps_overview_and_kd_by_keyword(self):
        def fake_post(url, body, timeout=120):
            if url == dataforseo.LABS_KEYWORD_OVERVIEW_URL:
                return _response([{
                    "keyword": "seo audit",
                    "keyword_info": {"search_volume": 500, "cpc": 2.5, "competition": 0.7},
                    "search_intent_info": {"main_intent": "commercial"},
                }])
            if url == dataforseo.LABS_BULK_KEYWORD_DIFFICULTY_URL:
                return _response([{"keyword": "seo audit", "keyword_difficulty": 61}])
            self.fail(f"Unexpected endpoint: {url}")

        with patch.object(dataforseo, "_post", side_effect=fake_post):
            result = dataforseo.get_keyword_research_metrics(["seo audit", "SEO Audit"], "United Kingdom", "en")

        self.assertEqual(result["errors"], {})
        self.assertEqual(result["metrics"]["seo audit"]["search_volume"], 500)
        self.assertEqual(result["metrics"]["seo audit"]["keyword_difficulty"], 61)
        self.assertEqual(result["metrics"]["seo audit"]["search_intent"], "commercial")


class KeywordResearchWorkflowTests(unittest.TestCase):
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
            self.project = Client(name="Example Project", domain="example.test")
            self.admin = User(username="admin", password_hash="not-used", role="admin")
            db.session.add_all([self.project, self.admin])
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

    def test_parse_input_enforces_mode_and_deduplicates(self):
        self.assertEqual(parse_input_keywords("SEO audit\nseo audit\nTechnical SEO", "bulk"), ["SEO audit", "Technical SEO"])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_input_keywords("one\ntwo", "single")
        with self.assertRaisesRegex(ValueError, "at most"):
            parse_input_keywords("\n".join(f"keyword {index}" for index in range(MAX_BULK_KEYWORDS + 1)), "bulk")

    def test_worker_persists_single_research_without_touching_snapshots(self):
        with self.app.app_context():
            run = KeywordResearchRun(
                client_id=self.project_id,
                created_by_user_id=self.admin_id,
                mode="single",
                input_keywords=["seo audit"],
                location="United Kingdom",
                language="en",
                status="pending",
                progress={},
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id

            discovery = {
                "keywords": [{"keyword": "seo audit template", "source_types": ["related"], "source_rank": 1}],
                "questions": [{"keyword": "How do I run an SEO audit?", "source_rank": 1}],
                "autocomplete": [{"keyword": "seo audit free", "source_rank": 1, "relevance": 1300}],
                "errors": {},
                "provider_cost": 0.04,
            }
            metrics = {
                "metrics": {
                    "seo audit": {"search_volume": 500, "keyword_difficulty": 61, "search_intent": "commercial"},
                    "seo audit template": {"search_volume": 90, "keyword_difficulty": 42},
                },
                "errors": {},
                "provider_cost": 0.02,
            }
            with patch("services.keyword_research.dataforseo.get_keyword_research_discovery", return_value=discovery), patch(
                "services.keyword_research.dataforseo.get_keyword_research_metrics", return_value=metrics,
            ):
                claimed_id = claim_next_keyword_research_run()
                self.assertEqual(claimed_id, run_id)
                completed = run_keyword_research(claimed_id)

            self.assertEqual(completed.status, "complete")
            self.assertEqual(completed.summary["keywords"], 2)
            self.assertEqual(completed.summary["questions"], 1)
            rows = KeywordResearchResult.query.filter_by(run_id=run_id).all()
            self.assertEqual({row.result_type for row in rows}, {"keyword", "question", "autocomplete"})
            self.assertEqual(KeywordResearchRun.query.count(), 1)
            # The test database has no snapshot because research cannot create one.
            from app.models import Snapshot
            self.assertEqual(Snapshot.query.count(), 0)

    def test_partial_provider_result_is_kept_and_reported(self):
        with self.app.app_context():
            run = KeywordResearchRun(
                created_by_user_id=self.admin_id,
                mode="bulk",
                input_keywords=["seo audit"],
                location="United Kingdom",
                language="en",
                status="pending",
                progress={},
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id
            with patch("services.keyword_research.dataforseo.get_keyword_research_metrics", return_value={
                "metrics": {"seo audit": {"search_volume": 500}},
                "errors": {"keyword_difficulty": {"message": "Provider did not return KD.", "retryable": True}},
                "provider_cost": 0.01,
            }):
                claimed_id = claim_next_keyword_research_run()
                completed = run_keyword_research(claimed_id)
            self.assertEqual(completed.status, "partial")
            self.assertEqual(completed.summary["keywords_with_metrics"], 1)
            self.assertIn("Keyword Difficulty", completed.error_message)

    def test_business_fit_is_explicit_and_reclassifies_saved_rows_without_provider_call(self):
        with self.app.app_context():
            run = KeywordResearchRun(
                client_id=self.project_id,
                created_by_user_id=self.admin_id,
                mode="single",
                input_keywords=["sell house fast"],
                location="United Kingdom",
                language="en",
                status="complete",
                progress={},
                summary={"keywords": 4},
            )
            db.session.add(run)
            db.session.flush()
            db.session.add_all([
                KeywordResearchResult(run_id=run.id, result_type="keyword", keyword="sell house fast", source_types=["input"], source_rank=0),
                KeywordResearchResult(run_id=run.id, result_type="keyword", keyword="cash buyer service", source_types=["related"], source_rank=1),
                KeywordResearchResult(run_id=run.id, result_type="keyword", keyword="buy to let mortgage", source_types=["related"], source_rank=2),
                KeywordResearchResult(run_id=run.id, result_type="keyword", keyword="estate agent fees", source_types=["suggestion"], source_rank=3),
            ])
            db.session.commit()
            run_id = run.id

        response = self.http_client.post(f"/keyword-research/{run_id}/business-fit", data={
            "focus_terms": "cash buyer, sell house",
            "exclude_terms": "mortgage, buy to let",
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            rows = {
                row.keyword: row
                for row in KeywordResearchResult.query.filter_by(run_id=run_id, result_type="keyword").all()
            }
            self.assertEqual(rows["sell house fast"].business_fit, "input")
            self.assertEqual(rows["cash buyer service"].business_fit, "aligned")
            self.assertEqual(rows["buy to let mortgage"].business_fit, "excluded")
            self.assertEqual(rows["estate agent fees"].business_fit, "review")
            self.assertEqual(rows["buy to let mortgage"].business_matches["exclude_terms"], ["mortgage", "buy to let"])

        shortlist = self.http_client.get(f"/keyword-research/{run_id}?fit=shortlist")
        self.assertEqual(shortlist.status_code, 200)
        self.assertIn(b"cash buyer service", shortlist.data)
        self.assertNotIn(b"buy to let mortgage", shortlist.data)

    def test_keyword_result_page_is_server_paginated_and_preserves_filters(self):
        with self.app.app_context():
            run = KeywordResearchRun(
                created_by_user_id=self.admin_id,
                mode="single",
                input_keywords=["cash buyer"],
                location="United Kingdom",
                language="en",
                status="complete",
                progress={},
                summary={"keywords": 31},
            )
            db.session.add(run)
            db.session.flush()
            for index in range(31):
                db.session.add(KeywordResearchResult(
                    run_id=run.id,
                    result_type="keyword",
                    keyword=f"cash buyer idea {index:02d}",
                    source_types=["related"],
                    source_rank=index + 1,
                    business_fit="aligned",
                    search_volume=100 + index,
                ))
            db.session.commit()
            run_id = run.id

        page_two = self.http_client.get(f"/keyword-research/{run_id}?fit=shortlist&sort=provider&page=2")
        self.assertEqual(page_two.status_code, 200)
        self.assertIn(b"Showing 26\xe2\x80\x9331 of 31 saved keyword ideas", page_two.data)
        self.assertIn(b"cash buyer idea 25", page_two.data)
        self.assertNotIn(b"cash buyer idea 00", page_two.data)
        self.assertIn(b"fit=shortlist", page_two.data)

    def test_routes_create_research_and_add_result_to_project_tracking(self):
        response = self.http_client.post("/keyword-research", data={
            "mode": "bulk",
            "keywords": "seo audit\ntechnical seo",
            "location": "United Kingdom",
            "language": "en",
            "client_id": str(self.project_id),
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            run = KeywordResearchRun.query.one()
            self.assertEqual(run.status, "pending")
            self.assertEqual(run.input_keywords, ["seo audit", "technical seo"])
            result = KeywordResearchResult(
                run_id=run.id,
                result_type="keyword",
                keyword="seo audit",
                source_types=["input"],
                search_volume=500,
                keyword_difficulty=61,
            )
            db.session.add(result)
            run.status = "complete"
            run.summary = {"keywords": 1, "keywords_with_metrics": 1, "questions": 0, "autocomplete": 0}
            db.session.commit()
            run_id, result_id = run.id, result.id

        state = self.http_client.get(f"/keyword-research/{run_id}/state")
        self.assertEqual(state.get_json()["status"], "complete")
        detail = self.http_client.get(f"/keyword-research/{run_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Keyword opportunities", detail.data)
        tracked = self.http_client.post(f"/keyword-research/{run_id}/results/{result_id}/track", data={"client_id": self.project_id})
        self.assertEqual(tracked.status_code, 302)
        with self.app.app_context():
            keyword = Keyword.query.filter_by(client_id=self.project_id, keyword="seo audit").one()
            self.assertEqual(keyword.location, "United Kingdom")
            self.assertEqual(keyword.language, "en")


if __name__ == "__main__":
    unittest.main()
