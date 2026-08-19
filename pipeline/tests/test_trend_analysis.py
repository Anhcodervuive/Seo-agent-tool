import datetime
import unittest
from types import SimpleNamespace

from services.trend_analysis import _latest_snapshot_point_per_day, _summary


class TrendSummaryTests(unittest.TestCase):
    def test_summary_reports_positive_change(self):
        summary = _summary([{"value": 100}, {"value": 125}])
        self.assertEqual(125, summary["latest"])
        self.assertEqual(25, summary["absolute_change"])
        self.assertEqual(25.0, summary["percent_change"])
        self.assertEqual("up", summary["health_direction"])

    def test_issue_reduction_is_positive_for_project_health(self):
        summary = _summary([{"value": 700}, {"value": 500}], inverse_health=True)
        self.assertEqual("down", summary["direction"])
        self.assertEqual("up", summary["health_direction"])

    def test_zero_baseline_has_no_infinite_percentage(self):
        summary = _summary([{"value": 0}, {"value": 10}])
        self.assertIsNone(summary["percent_change"])

    def test_empty_series_has_stable_shape(self):
        summary = _summary([])
        self.assertIsNone(summary["latest"])
        self.assertEqual(0, summary["data_points"])

    def test_same_day_audits_keep_the_latest_observation(self):
        snapshots = [
            SimpleNamespace(id=10, created_at=datetime.datetime(2026, 8, 19, 9, 0)),
            SimpleNamespace(id=11, created_at=datetime.datetime(2026, 8, 19, 15, 0)),
        ]
        points = _latest_snapshot_point_per_day(snapshots, {10: 700, 11: 500})
        self.assertEqual([{"date": "2026-08-19", "value": 500, "snapshot_id": 11}], points)


if __name__ == "__main__":
    unittest.main()
