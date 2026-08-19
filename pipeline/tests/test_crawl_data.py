import unittest

from services.crawl_data import normalize_crawl_export, normalize_url


class CrawlDataTests(unittest.TestCase):
    def test_normalize_url_removes_host_noise_and_fragment(self):
        self.assertEqual("https://example.com/path?a=1", normalize_url(" HTTPS://EXAMPLE.COM/path/?a=1#section "))
        self.assertIsNone(normalize_url("https://example.com:bad"))
        self.assertIsNone(normalize_url(""))

    def test_export_skips_invalid_rows_and_deduplicates(self):
        result = normalize_crawl_export({
            "urls": [{"url": "https://EXAMPLE.com/"}, {"url": "https://example.com"}, {"url": ""}],
            "links": [
                {"source_url": "https://example.com/", "target_url": "https://example.com/a", "anchor_text": "A"},
                {"source_url": "https://example.com", "target_url": "https://example.com/a", "anchor_text": "A"},
                {"source_url": "", "target_url": "https://example.com/a"},
            ],
            "issues": [
                {"url": "https://example.com/", "issue": "Missing title", "type": "warning"},
                {"url": "https://example.com", "issue": "Missing title", "type": "warning"},
                {"url": "https://example.com", "type": "warning"},
            ],
        })
        self.assertEqual(1, len(result["urls"]))
        self.assertEqual(1, len(result["links"]))
        self.assertEqual(1, len(result["issues"]))
        self.assertEqual(1, result["quality"]["duplicate_urls_removed"])
        self.assertEqual(1, result["quality"]["invalid_urls_removed"])


if __name__ == "__main__":
    unittest.main()
