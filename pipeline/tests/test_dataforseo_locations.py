import unittest

from services.dataforseo_locations import (
    GOOGLE_LOCATIONS,
    normalize_competitor_traffic_locations,
    normalize_google_location,
)
from app.routes.admin import parse_keywords_input


class DataForSeoLocationTests(unittest.TestCase):
    def test_catalogue_contains_canonical_united_kingdom(self):
        self.assertGreaterEqual(len(GOOGLE_LOCATIONS), 200)
        self.assertEqual(normalize_google_location("united kingdom"), "United Kingdom")

    def test_rejects_typo_with_actionable_message(self):
        with self.assertRaisesRegex(ValueError, "United Kingdon"):
            normalize_google_location("United Kingdon")

    def test_bulk_parser_rejects_invalid_inline_location(self):
        with self.assertRaisesRegex(ValueError, "Keyword line 1"):
            parse_keywords_input("sell house fast|high|desktop|United Kingdon|en", "United Kingdom")

    def test_bulk_parser_canonicalizes_location_case(self):
        rows = parse_keywords_input("sell house fast|high|desktop|united kingdom|en", "United States")
        self.assertEqual(rows[0]["location"], "United Kingdom")

    def test_competitor_markets_include_primary_and_deduplicate(self):
        markets = normalize_competitor_traffic_locations(
            ["United States", "united kingdom", "United Kingdom"],
            "United States",
        )
        self.assertEqual(["United States", "United Kingdom"], markets)
