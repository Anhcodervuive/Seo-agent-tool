"""Small, testable REST client for the LibreCrawl service.

This module intentionally contains transport concerns only. Snapshot/database
mapping stays in ``pipeline_runner`` so the same client can later be used by
MCP adapters, AI tools, or a dashboard refresh endpoint.
"""

from dataclasses import dataclass
import time

import requests


class LibreCrawlError(RuntimeError):
    """Raised when LibreCrawl cannot start, complete, or return a crawl."""


@dataclass(frozen=True)
class CrawlPoll:
    """One normalized status observation from LibreCrawl."""

    crawl_state: dict
    live_state: dict | None
    status: str | None
    poll_number: int


class LibreCrawlClient:
    """REST client shared by pipeline-facing integrations."""

    def __init__(self, base_url, *, timeout=120, poll_interval=5, max_polls=60, session=None):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = int(timeout)
        self.poll_interval = max(0, int(poll_interval))
        self.max_polls = max(1, int(max_polls))
        self.session = session or requests.Session()

    def _url(self, path):
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _json(response):
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise LibreCrawlError("LibreCrawl returned a non-JSON response.") from exc

    def guest_login(self):
        return self._json(self.session.post(self._url("/api/guest-login"), json={}, timeout=self.timeout))

    def start_crawl(self, target_url, *, seed_urls=None, crawl_scope=None):
        payload = {
            "url": target_url,
            "seed_urls": seed_urls or [],
            "crawl_scope": crawl_scope or {},
        }
        data = self._json(self.session.post(self._url("/api/start_crawl"), json=payload, timeout=self.timeout))
        if not data.get("success") or not data.get("crawl_id"):
            raise LibreCrawlError(f"crawl start failed: {data}")
        return data

    def get_crawl(self, crawl_id):
        return self._json(self.session.get(self._url(f"/api/crawls/{crawl_id}"), timeout=self.timeout))

    def get_live_status(self):
        return self._json(self.session.get(self._url("/api/crawl_status"), timeout=self.timeout))

    def wait_for_completion(self, crawl_id, *, on_poll=None):
        """Poll until the crawl completes and return its final state."""
        for poll_number in range(1, self.max_polls + 1):
            if self.poll_interval:
                time.sleep(self.poll_interval)
            crawl_state = self.get_crawl(crawl_id)
            live_state = None
            try:
                live_state = self.get_live_status()
            except (requests.RequestException, ValueError, LibreCrawlError):
                # The persisted crawl endpoint is enough to import results.
                live_state = None
            observation = CrawlPoll(
                crawl_state=crawl_state,
                live_state=live_state,
                status=(crawl_state.get("crawl", {}) or {}).get("status"),
                poll_number=poll_number,
            )
            if on_poll:
                on_poll(observation)
            if observation.status == "completed":
                return crawl_state
        raise LibreCrawlError(
            f"crawl did not complete within {self.max_polls * self.poll_interval} seconds"
        )

