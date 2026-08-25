import unittest

from services.pipeline_status import final_snapshot_status, load_notes, stage_summary
from services.pipeline_runner import _ranking_counts


class PipelineStatusTests(unittest.TestCase):
    def test_invalid_notes_are_safe(self):
        self.assertEqual(load_notes("not-json"), {})
        self.assertEqual(load_notes("[]"), {})
        self.assertEqual(load_notes('{"progress": {"phase": "crawl"}}')["progress"]["phase"], "crawl")

    def test_optional_failure_is_partial(self):
        stages = [
            {"name": "crawl", "status": "complete", "optional": False},
            {"name": "ga4", "status": "failed", "optional": True, "error": "quota"},
        ]
        self.assertEqual(final_snapshot_status(stages), "partial")

    def test_stage_that_returns_partial_makes_snapshot_partial(self):
        stages = [
            {"name": "crawl", "status": "complete", "optional": False},
            {"name": "rankings", "status": "partial", "optional": True},
        ]
        self.assertEqual(final_snapshot_status(stages), "partial")

    def test_ranking_summary_does_not_count_provider_failures_as_not_ranking(self):
        counts = _ranking_counts({
            "completed": {
                "found": {"status": "found"},
                "not-found": {"status": "not_found"},
                "failed": {"status": "failed"},
            },
        })

        self.assertEqual(3, counts["rows"])
        self.assertEqual(1, counts["ranked_rows"])
        self.assertEqual(1, counts["not_ranking_rows"])
        self.assertEqual(1, counts["failed_rows"])

    def test_required_failure_is_retryable(self):
        stages = [{"name": "crawl", "status": "failed", "optional": False, "error": "timeout"}]
        self.assertEqual(final_snapshot_status(stages), "failed")

    def test_stage_summary_drops_non_serializable_runtime_values(self):
        summary = stage_summary([{
            "name": "crawl", "status": "complete", "duration_seconds": 1.2,
            "value": object(), "error": None, "optional": False,
        }])
        self.assertEqual(summary, [{
            "name": "crawl", "status": "complete", "duration_seconds": 1.2,
            "error": None, "optional": False,
        }])


if __name__ == "__main__":
    unittest.main()
