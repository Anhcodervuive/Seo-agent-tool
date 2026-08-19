import unittest

from services.librecrawl_client import LibreCrawlClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.poll_count = 0

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse({"success": True, "crawl_id": 42})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/api/crawl_status"):
            return FakeResponse({"stats": {"crawled": self.poll_count}})
        self.poll_count += 1
        status = "completed" if self.poll_count >= 2 else "running"
        return FakeResponse({"crawl": {"status": status, "urls_crawled": self.poll_count}})


class LibreCrawlClientTests(unittest.TestCase):
    def test_start_payload_contains_scope(self):
        session = FakeSession()
        client = LibreCrawlClient("http://crawler", session=session, poll_interval=0)
        client.guest_login()
        result = client.start_crawl(
            "https://example.com",
            seed_urls=["https://example.com/a"],
            crawl_scope={"mode": "selected_urls"},
        )
        self.assertEqual(result["crawl_id"], 42)
        self.assertEqual(session.calls[1][2]["json"]["crawl_scope"]["mode"], "selected_urls")

    def test_wait_reports_progress_and_returns_final_state(self):
        session = FakeSession()
        observations = []
        client = LibreCrawlClient("http://crawler", session=session, poll_interval=0, max_polls=3)
        final = client.wait_for_completion(42, on_poll=observations.append)
        self.assertEqual(final["crawl"]["status"], "completed")
        self.assertEqual([item.status for item in observations], ["running", "completed"])


if __name__ == "__main__":
    unittest.main()
