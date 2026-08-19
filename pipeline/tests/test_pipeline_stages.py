import unittest

from services.pipeline_stages import StageSpec, build_stage_plan, execute_stage


class PipelineStageTests(unittest.TestCase):
    def test_full_audit_has_stable_order(self):
        plan = build_stage_plan(
            "full_audit",
            crawl=lambda: 1,
            ga4=lambda: 2,
            gsc=lambda: 3,
            rankings=lambda: 4,
            backlinks=lambda: 5,
            competitor_insights=lambda: 6,
        )
        self.assertEqual(
            [stage.name for stage in plan],
            ["crawl", "ga4", "gsc", "rankings", "backlinks", "competitor_insights"],
        )
        self.assertFalse(plan[0].optional)

    def test_rank_check_only_runs_rankings(self):
        plan = build_stage_plan(
            "rank_check",
            crawl=lambda: 1,
            ga4=lambda: 2,
            gsc=lambda: 3,
            rankings=lambda: 4,
            backlinks=lambda: 5,
            competitor_insights=lambda: 6,
        )
        self.assertEqual([stage.name for stage in plan], ["rankings"])
        self.assertEqual(plan[0].run(), 4)

    def test_errors_are_structured_and_do_not_escape_stage_boundary(self):
        execution = execute_stage(StageSpec("gsc", lambda: (_ for _ in ()).throw(RuntimeError("quota"))))
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(execution["error"], "quota")
        self.assertGreaterEqual(execution["duration_seconds"], 0)

    def test_stage_returning_errors_is_partial(self):
        execution = execute_stage(StageSpec("rankings", lambda: {"rows": 1, "errors": ["one timeout"]}))
        self.assertEqual(execution["status"], "partial")


if __name__ == "__main__":
    unittest.main()
