import unittest
from unittest.mock import patch

from services import dataforseo


class KeywordRankingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
