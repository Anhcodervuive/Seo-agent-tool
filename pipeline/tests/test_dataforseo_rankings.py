import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import dataforseo


class KeywordRankingTests(unittest.TestCase):
    @patch.object(dataforseo, "_headers", return_value={"Authorization": "Basic test"})
    @patch.object(dataforseo.requests, "request")
    def test_provider_error_keeps_http_and_dataforseo_codes_for_logs(self, request, _headers):
        error = dataforseo.requests.HTTPError("Bad provider response")
        error.response = SimpleNamespace(
            status_code=200,
            json=lambda: {"status_code": 40101, "status_message": "Internal SE Server Error."},
        )
        request.side_effect = error

        with self.assertRaises(dataforseo.DataForSEOError) as context:
            dataforseo._request_json("POST", dataforseo.SERP_TASK_POST_URL, [])

        diagnostic = context.exception.diagnostic()
        self.assertEqual(200, diagnostic["http_status"])
        self.assertEqual(40101, diagnostic["provider_status_code"])
        self.assertTrue(diagnostic["retryable"])

    @patch.object(dataforseo, "_post")
    def test_ranking_matches_www_domain_and_uses_organic_rank(self, post):
        post.return_value = {
            "cost": 0.01,
            "tasks": [{"result": [{"items": [
                {"type": "organic", "domain": "other.example", "url": "https://other.example", "rank_group": 1},
                {
                    "type": "organic",
                    "domain": "www.example.com",
                    "url": "https://www.example.com/pricing",
                    "rank_group": 4,
                    "rank_absolute": 6,
                },
            ]}]}],
        }

        result, cost = dataforseo.get_keyword_ranking("example keyword", "example.com")

        self.assertEqual(0.01, cost)
        self.assertEqual("found", result["status"])
        self.assertEqual(4, result["position"])
        self.assertEqual("https://www.example.com/pricing", result["url"])
        self.assertNotIn("target", post.call_args.args[1][0])

    @patch.object(dataforseo, "_post")
    def test_ranking_reports_not_found_only_after_successful_serp_response(self, post):
        post.return_value = {"cost": 0.01, "tasks": [{"result": [{"items": []}]}]}

        result, _ = dataforseo.get_keyword_ranking("example keyword", "example.com")

        self.assertEqual({"status": "not_found", "position": None, "url": None}, result)

    @patch.object(dataforseo, "_request_json")
    def test_standard_ranking_tasks_are_batched_and_correlated_by_tag(self, request_json):
        def queued_response(_method, _url, body, **_kwargs):
            return {
                "tasks": [
                    {
                        "id": f"task-{item['tag']}",
                        "status_code": 20100,
                        "data": {"tag": item["tag"]},
                    }
                    for item in body
                ],
            }

        request_json.side_effect = queued_response
        checks = [
            {
                "id": f"check-{index}",
                "keyword": f"keyword {index}",
                "location": "United Kingdom",
                "language": "en",
                "device": "desktop",
            }
            for index in range(101)
        ]

        result = dataforseo.queue_keyword_ranking_tasks(checks)

        self.assertEqual(101, len(result["queued"]))
        self.assertEqual({}, result["failed"])
        self.assertEqual("task-check-100", result["queued"]["check-100"]["task_id"])
        self.assertEqual([100, 1], [len(call.args[2]) for call in request_json.call_args_list])
        self.assertEqual("check-0", request_json.call_args_list[0].args[2][0]["tag"])
        self.assertNotIn("target", request_json.call_args_list[0].args[2][0])

    def test_standard_task_payload_accepts_explicit_high_priority(self):
        payload = dataforseo._ranking_task_payload({
            "id": "check-1",
            "keyword": "houses",
            "location": "United Kingdom",
            "language": "en",
            "device": "desktop",
            "priority": 2,
        })

        self.assertEqual(2, payload["priority"])

    def test_standard_task_payload_keeps_cost_preserving_default_implicit(self):
        payload = dataforseo._ranking_task_payload({
            "id": "check-1",
            "keyword": "houses",
            "location": "United Kingdom",
            "language": "en",
            "device": "desktop",
        })

        self.assertNotIn("priority", payload)

    @patch.object(dataforseo, "_request_json")
    def test_standard_task_submission_keeps_provider_failure_separate(self, request_json):
        request_json.return_value = {
            "tasks": [{
                "id": "provider-task",
                "status_code": 40101,
                "status_message": "Internal SE Server Error.",
            }],
        }

        result = dataforseo.queue_keyword_ranking_tasks([{
            "id": "check-1", "keyword": "houses", "location": "United Kingdom",
            "language": "en", "device": "desktop",
        }])

        self.assertEqual({}, result["queued"])
        diagnostic = result["failed"]["check-1"]
        self.assertEqual(40101, diagnostic["provider_status_code"])
        self.assertTrue(diagnostic["retryable"])
        self.assertEqual("provider-task", diagnostic["task_id"])

    @patch.object(dataforseo, "_request_json")
    def test_standard_task_result_matches_domain_locally(self, request_json):
        request_json.return_value = {
            "cost": 0.012,
            "tasks": [{
                "id": "task-1",
                "status_code": 20000,
                "result": [{"items": [
                    {"type": "organic", "domain": "other.example", "rank_group": 1},
                    {
                        "type": "organic", "domain": "www.example.com",
                        "url": "https://www.example.com/pricing",
                        "rank_group": 7,
                    },
                ]}],
            }],
        }

        result, cost = dataforseo.get_keyword_ranking_task_result("task-1", "example.com")

        self.assertEqual(0.012, cost)
        self.assertEqual("found", result["status"])
        self.assertEqual(7, result["position"])
        self.assertEqual("https://www.example.com/pricing", result["url"])

    @patch.object(dataforseo, "_request_json")
    def test_standard_task_pending_is_not_recorded_as_not_found(self, request_json):
        request_json.return_value = {
            "tasks": [{
                "id": "task-1",
                "status_code": 40601,
                "status_message": "Task Handed.",
            }],
        }

        with self.assertRaises(dataforseo.DataForSEOTaskPending) as context:
            dataforseo.get_keyword_ranking_task_result("task-1", "example.com")

        self.assertTrue(context.exception.retryable)
        self.assertEqual(40601, context.exception.provider_status_code)

    @patch.object(dataforseo, "_request_json")
    def test_ready_task_ids_are_read_from_standard_tasks_ready_response(self, request_json):
        request_json.return_value = {
            "tasks": [{"result": [{"id": "task-1"}, {"task_id": "task-2"}]}],
        }

        self.assertEqual({"task-1", "task-2"}, dataforseo.get_ready_keyword_ranking_task_ids())

    @patch.object(dataforseo, "_post")
    def test_search_volume_is_keyed_by_keyword_location_and_language(self, post):
        post.return_value = {
            "cost": 0.02,
            "tasks": [
                {"result": [{"keyword": "houses", "search_volume": 1200}]},
                {"result": [{"keyword": "houses", "search_volume": 400}]},
            ],
        }

        result, cost = dataforseo.enrich_keyword_contexts([
            {"keyword": "houses", "location": "United Kingdom", "language": "en"},
            {"keyword": "houses", "location": "Germany", "language": "de"},
        ])

        self.assertEqual(0.02, cost)
        self.assertEqual(1200, result[("houses", "united kingdom", "en")]["search_volume"])
        self.assertEqual(400, result[("houses", "germany", "de")]["search_volume"])
        body = post.call_args.args[1]
        self.assertEqual("United Kingdom", body[0]["location_name"])
        self.assertEqual("de", body[1]["language_code"])

    @patch.object(dataforseo, "_post")
    def test_competitor_country_traffic_reads_one_market_overview(self, post):
        post.return_value = {
            "cost": 0.01,
            "tasks": [{"result": [{"metrics": {"organic": {
                "etv": 125.5,
                "count": 42,
                "pos_1": 2,
                "pos_2_3": 3,
                "pos_4_10": 5,
                "estimated_paid_traffic_cost": 88.25,
            }}}]}],
        }

        result, cost = dataforseo.get_competitor_country_traffic("example.com", "United Kingdom")

        self.assertEqual(0.01, cost)
        self.assertEqual("United Kingdom", result["location"])
        self.assertEqual(125.5, result["estimated_organic_traffic"])
        self.assertEqual(42, result["organic_keyword_count"])
        self.assertEqual(10, result["top_10_keyword_count"])
        self.assertEqual("United Kingdom", post.call_args.args[1][0]["location_name"])

    @patch.object(dataforseo, "_post")
    def test_competitor_insights_keeps_other_datasets_when_top_pages_fails(self, post):
        def side_effect(url, _payload):
            if url == dataforseo.LABS_RELEVANT_PAGES_URL:
                raise RuntimeError("500 Server Error: Internal Server Error")
            if url == dataforseo.LABS_RANKED_KEYWORDS_URL:
                return {"cost": 0.01, "tasks": [{"result": [{"items": []}]}]}
            return {"cost": 0.02, "tasks": [{"result": [{"organic": {"etv": 50, "count": 8}}]}]}

        post.side_effect = side_effect

        result, cost = dataforseo.get_competitor_insights("example.com", "United Kingdom")

        self.assertEqual(0.03, cost)
        self.assertEqual([], result["top_pages"])
        self.assertEqual(8, result["summary"]["organic_keyword_count"])
        self.assertIn("top organic pages", result["dataset_errors"])


if __name__ == "__main__":
    unittest.main()
