import datetime
import unittest
from types import SimpleNamespace

from services.rankings import _build_rows, _matches_filter, ranking_movement


def snapshot(snapshot_id, day, status="complete"):
    return SimpleNamespace(
        id=snapshot_id,
        created_at=datetime.datetime(2026, 8, day),
        status=status,
    )


def keyword(keyword_id, value, location="United States", device="desktop", language="en"):
    return SimpleNamespace(
        id=keyword_id,
        keyword=value,
        location=location,
        device=device,
        language=language,
        priority="medium",
    )


def ranking(row_id, snapshot_id, value, position, status="found", competitor_id=None):
    return SimpleNamespace(
        id=row_id,
        snapshot_id=snapshot_id,
        keyword=value,
        location="United States",
        device="desktop",
        language="en",
        competitor_id=competitor_id,
        position=position,
        search_volume=100,
        url=f"https://example.com/{value.replace(' ', '-')}",
        check_status=status,
        error_message=None,
    )


class RankingServiceTests(unittest.TestCase):
    def test_movement_handles_improvement_loss_new_and_missing(self):
        self.assertEqual((4, "up"), (ranking_movement(4, 8)["value"], ranking_movement(4, 8)["direction"]))
        self.assertEqual((-4, "down"), (ranking_movement(8, 4)["value"], ranking_movement(8, 4)["direction"]))
        self.assertEqual("new", ranking_movement(4, None)["direction"])
        self.assertEqual("lost", ranking_movement(None, 4)["direction"])
        self.assertEqual("failed", ranking_movement(None, 4, "failed")["direction"])

    def test_build_rows_uses_snapshot_history_and_excludes_competitors(self):
        latest = snapshot(55, 19)
        previous = snapshot(53, 1)
        oldest = snapshot(51, 1)
        rows = _build_rows(
            [keyword(1, "seo tools"), keyword(2, "lost keyword")],
            [latest, previous, oldest],
            [
                ranking(1, 55, "seo tools", 4),
                ranking(2, 53, "seo tools", 8),
                ranking(3, 51, "seo tools", 12),
                ranking(4, 53, "lost keyword", 5),
                ranking(5, 55, "seo tools", 99, competitor_id=7),
            ],
        )
        self.assertEqual(2, len(rows))
        self.assertEqual(4, rows[0]["latest_position"])
        self.assertEqual(8, rows[0]["previous_position"])
        self.assertEqual([12, 8, 4], [point["position"] for point in rows[0]["history"]])
        self.assertTrue(_matches_filter(rows[0], "winners"))
        self.assertTrue(_matches_filter(rows[0], "page_1"))
        self.assertTrue(_matches_filter(rows[1], "not_ranking"))

    def test_missing_current_ranking_is_not_zero(self):
        rows = _build_rows(
            [keyword(1, "lost keyword")],
            [snapshot(55, 19), snapshot(53, 1)],
            [ranking(1, 53, "lost keyword", 5)],
        )
        self.assertIsNone(rows[0]["latest_position"])
        self.assertEqual("Lost", rows[0]["movement_label"])


if __name__ == "__main__":
    unittest.main()
