import unittest
from unittest.mock import patch

from services.link_validation import _validate_target, enrich_crawl_link_statuses


class FakeResponse:
    def __init__(self, status_code, url, history=None):
        self.status_code = status_code
        self.url = url
        self.history = history or []
        self.closed = False

    def close(self):
        self.closed = True


class LinkValidationTests(unittest.TestCase):
    def test_enrichment_reuses_crawl_results_and_deduplicates_network_checks(self):
        payload = {
            "urls": [
                {"url": "https://site.test/missing", "status_code": 404, "crawled_at": "now"},
            ],
            "links": [
                {"source_url": "https://site.test/a", "target_url": "https://site.test/missing"},
                {"source_url": "https://site.test/a", "target_url": "https://outside.test/server-error"},
                {"source_url": "https://site.test/b", "target_url": "https://outside.test/server-error"},
                {"source_url": "https://site.test/b", "target_url": "https://outside.test/timeout"},
                {"source_url": "https://site.test/b", "target_url": "https://outside.test/gone", "target_status": 410},
                {"source_url": "https://site.test/b", "target_url": "mailto:help@site.test"},
            ],
        }
        calls = []

        def validator(target_url, **_kwargs):
            calls.append(target_url)
            if target_url.endswith("timeout"):
                return {
                    "target_status": 0,
                    "target_status_source": "validator",
                    "target_error_type": "timeout",
                    "target_error_message": "timed out",
                }
            return {
                "target_status": 503,
                "target_status_source": "validator",
                "target_error_type": None,
                "target_error_message": None,
            }

        summary = enrich_crawl_link_statuses(payload, workers=4, validator=validator)

        self.assertCountEqual(calls, [
            "https://outside.test/server-error",
            "https://outside.test/timeout",
        ])
        self.assertEqual(404, payload["links"][0]["target_status"])
        self.assertEqual("crawl", payload["links"][0]["target_status_source"])
        self.assertEqual(503, payload["links"][1]["target_status"])
        self.assertEqual(503, payload["links"][2]["target_status"])
        self.assertEqual(0, payload["links"][3]["target_status"])
        self.assertEqual("skipped", payload["links"][5]["target_status_source"])
        self.assertEqual(2, summary["validated_targets"])
        self.assertEqual(1, summary["broken_targets"])
        self.assertEqual(1, summary["unreachable_targets"])
        self.assertEqual(1, summary["reused_page_targets"])
        self.assertEqual(1, summary["crawler_status_targets"])
        self.assertEqual(1, summary["skipped_targets"])

    def test_disabled_validation_still_reuses_known_page_statuses(self):
        payload = {
            "urls": [{"url": "https://site.test/found", "status_code": 200}],
            "links": [
                {"source_url": "https://site.test", "target_url": "https://site.test/found"},
                {"source_url": "https://site.test", "target_url": "https://outside.test/unknown"},
            ],
        }
        summary = enrich_crawl_link_statuses(payload, enabled=False)
        self.assertEqual(200, payload["links"][0]["target_status"])
        self.assertNotIn("target_status", payload["links"][1])
        self.assertEqual(0, summary["validated_targets"])

    def test_head_failure_is_verified_with_streamed_get(self):
        head = FakeResponse(405, "https://outside.test/resource")
        get = FakeResponse(200, "https://outside.test/final", history=[head])

        class FakeSession:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                return head if method == "HEAD" else get

        session = FakeSession()
        with patch("services.link_validation._session", return_value=session):
            result = _validate_target(
                "https://outside.test/resource",
                timeout_seconds=3,
                allow_private_hosts=True,
            )

        self.assertEqual(["HEAD", "GET"], [call[0] for call in session.calls])
        self.assertTrue(session.calls[1][2]["stream"])
        self.assertEqual(200, result["target_status"])
        self.assertEqual("https://outside.test/final", result["target_final_url"])
        self.assertEqual(1, result["target_redirect_count"])


if __name__ == "__main__":
    unittest.main()
