import unittest

from services.pipeline_status import final_snapshot_status, load_notes, stage_summary


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
