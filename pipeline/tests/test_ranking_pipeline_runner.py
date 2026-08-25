import datetime
import json
import time
import unittest
from unittest.mock import patch

from flask import Flask

from app.models import Client, Keyword, Ranking, RankingReconciliationJob, Snapshot, db
from services import pipeline_runner


class RankingPipelineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SECRET_KEY="test-secret",
        )
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        self.client = Client(name="Example", domain="example.com", location="United Kingdom")
        db.session.add(self.client)
        db.session.flush()
        db.session.add_all([
            Keyword(client_id=self.client.id, keyword="first keyword", location="United Kingdom", language="en"),
            Keyword(client_id=self.client.id, keyword="second keyword", location="United Kingdom", language="en"),
        ])
        self.snapshot = Snapshot(client_id=self.client.id, status="running", notes=json.dumps({"progress": {}}))
        db.session.add(self.snapshot)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    @patch.object(pipeline_runner, "get_keyword_ranking_task_result")
    @patch.object(pipeline_runner, "get_ready_keyword_ranking_task_ids")
    @patch.object(pipeline_runner, "queue_keyword_ranking_tasks")
    @patch.object(pipeline_runner, "enrich_keyword_contexts")
    def test_standard_task_results_are_persisted_without_false_not_ranking(
        self,
        enrich,
        queue,
        ready_task_ids,
        get_task_result,
    ):
        enrich.return_value = ({
            ("first keyword", "united kingdom", "en"): {"search_volume": 100},
            ("second keyword", "united kingdom", "en"): {"search_volume": 200},
        }, 0.02)

        def queue_tasks(checks):
            return {
                "queued": {
                    check["id"]: {"task_id": f"task-{index}"}
                    for index, check in enumerate(checks, start=1)
                },
                "failed": {},
            }

        queue.side_effect = queue_tasks
        ready_task_ids.return_value = {"task-1", "task-2"}
        def task_result(task_id, _target):
            if task_id == "task-1":
                return {"status": "found", "position": 4, "url": "https://example.com/first"}, 0.01
            return {"status": "not_found", "position": None, "url": None}, 0.01

        get_task_result.side_effect = task_result

        result = pipeline_runner._pull_rankings(self.snapshot, self.client)

        self.assertEqual(2, result["rows"])
        self.assertEqual(1, result["ranked_rows"])
        self.assertEqual(1, result["not_ranking_rows"])
        self.assertEqual(0, result["failed_rows"])
        self.assertEqual([], result["errors"])
        self.assertEqual(0.04, result["cost"])
        rows = Ranking.query.filter_by(snapshot_id=self.snapshot.id).order_by(Ranking.keyword).all()
        self.assertEqual(["found", "not_found"], [row.check_status for row in rows])
        self.assertEqual([100, 200], [row.search_volume for row in rows])
        self.assertNotIn("ranking_task_state", json.loads(self.snapshot.notes))

    @patch.object(pipeline_runner, "get_keyword_ranking_task_result")
    @patch.object(pipeline_runner, "get_ready_keyword_ranking_task_ids")
    @patch.object(pipeline_runner, "queue_keyword_ranking_tasks")
    @patch.object(pipeline_runner, "enrich_keyword_contexts")
    def test_result_retrieval_is_bounded_and_concurrent(
        self,
        enrich,
        queue,
        ready_task_ids,
        get_task_result,
    ):
        db.session.add_all([
            Keyword(client_id=self.client.id, keyword=f"keyword {index}", location="United Kingdom", language="en")
            for index in range(3, 13)
        ])
        db.session.commit()
        enrich.return_value = ({}, 0.0)

        def queue_tasks(checks):
            return {
                "queued": {
                    check["id"]: {"task_id": f"task-{index}"}
                    for index, check in enumerate(checks, start=1)
                },
                "failed": {},
            }

        queue.side_effect = queue_tasks
        ready_task_ids.return_value = {f"task-{index}" for index in range(1, 13)}

        def slow_result(_task_id, _target):
            time.sleep(0.20)
            return {"status": "not_found", "position": None, "url": None}, 0.01

        get_task_result.side_effect = slow_result
        started = time.monotonic()
        with patch.object(pipeline_runner, "RANKING_RESULT_WORKERS", 6):
            result = pipeline_runner._pull_rankings(self.snapshot, self.client)
        elapsed = time.monotonic() - started

        self.assertEqual(12, result["rows"])
        self.assertEqual(12, result["not_ranking_rows"])
        # Serial retrieval needs roughly 2.4s. Six bounded workers should
        # finish two waves plus normal database overhead, well below that.
        self.assertLess(elapsed, 1.60)

    @patch.object(pipeline_runner, "queue_keyword_ranking_tasks")
    @patch.object(pipeline_runner, "enrich_keyword_contexts")
    def test_background_submission_is_reused_by_later_ranking_stage(self, enrich, queue):
        enrich.return_value = ({}, 0.0)

        def queue_tasks(checks):
            return {
                "queued": {
                    check["id"]: {"task_id": f"task-{index}"}
                    for index, check in enumerate(checks, start=1)
                },
                "failed": {},
            }

        queue.side_effect = queue_tasks

        state, total, resumed, targets = pipeline_runner._start_ranking_tasks(
            self.snapshot,
            self.client,
            background=True,
        )
        reused_state, reused_total, reused, reused_targets = pipeline_runner._start_ranking_tasks(
            self.snapshot,
            self.client,
        )

        self.assertEqual(2, total)
        self.assertEqual(1, targets)
        self.assertFalse(resumed)
        self.assertTrue(state["started_in_background"])
        self.assertEqual(state["task_ids"], reused_state["task_ids"])
        self.assertEqual(total, reused_total)
        self.assertEqual(targets, reused_targets)
        self.assertTrue(reused)
        self.assertEqual(1, queue.call_count)
        progress = json.loads(self.snapshot.notes)["progress"]
        self.assertEqual("processing", progress["ranking_state"])
        self.assertEqual(2, progress["ranking_submitted"])
        self.assertEqual(2, progress["ranking_total"])

    def _pending_ranking_state(self, *, foreground_wait_until, provider_wait_until):
        keyword = Keyword.query.filter_by(client_id=self.client.id).first()
        check_id = pipeline_runner._ranking_check_id(self.snapshot.id, None, keyword.id)
        return {
            "version": 1,
            "transport": "dataforseo_standard_tasks",
            "priority": 1,
            "checks": {
                check_id: {
                    "id": check_id,
                    "competitor_id": None,
                    "target": self.client.domain,
                    "keyword": keyword.keyword,
                    "location": keyword.location,
                    "language": keyword.language,
                    "device": keyword.device,
                    "search_volume": 100,
                },
            },
            "task_ids": {check_id: "task-1"},
            "completed": {},
            "warnings": [],
            "enrichment_cost": 0.0,
            "ranking_cost": 0.0,
            "submitted_at": time_to_iso(-60),
            "foreground_wait_until": foreground_wait_until,
            "provider_wait_until": provider_wait_until,
        }

    def _save_pending_state(self, state, *, status="running", stage_results=None):
        notes = {
            "progress": {},
            "ranking_task_state": state,
            "run": {"type": "rank_check"},
        }
        if stage_results is not None:
            notes["stage_results"] = stage_results
        self.snapshot.status = status
        self.snapshot.notes = json.dumps(notes)
        db.session.commit()

    @patch.object(pipeline_runner, "get_ready_keyword_ranking_task_ids", return_value=set())
    def test_foreground_timeout_defers_provider_tasks_without_marking_them_failed(self, _ready_task_ids):
        state = self._pending_ranking_state(
            foreground_wait_until=time_to_iso(-1),
            provider_wait_until=time_to_iso(600),
        )
        self._save_pending_state(state)

        result = pipeline_runner._pull_rankings(self.snapshot, self.client)

        self.assertTrue(result["deferred"])
        self.assertEqual(1, result["deferred_rows"])
        self.assertEqual(0, result["failed_rows"])
        self.assertEqual(0, Ranking.query.filter_by(snapshot_id=self.snapshot.id).count())
        self.assertIsNotNone(RankingReconciliationJob.query.filter_by(snapshot_id=self.snapshot.id).first())
        notes = json.loads(self.snapshot.notes)
        self.assertIn("ranking_task_state", notes)
        self.assertEqual("background_processing", notes["progress"]["ranking_state"])

    @patch.object(pipeline_runner, "get_keyword_ranking_task_result")
    @patch.object(pipeline_runner, "get_ready_keyword_ranking_task_ids", return_value={"task-1"})
    def test_reconciliation_collects_ready_results_and_completes_snapshot(self, _ready_task_ids, task_result):
        state = self._pending_ranking_state(
            foreground_wait_until=time_to_iso(-60),
            provider_wait_until=time_to_iso(600),
        )
        self._save_pending_state(
            state,
            status="partial",
            stage_results=[
                {"name": "rankings", "status": "partial", "optional": True, "duration_seconds": 0, "error": "Still processing"},
            ],
        )
        db.session.add(RankingReconciliationJob(
            snapshot_id=self.snapshot.id,
            client_id=self.client.id,
            status="pending",
            next_poll_at=datetime.datetime.utcnow() - datetime.timedelta(seconds=1),
        ))
        db.session.commit()
        task_result.return_value = ({"status": "found", "position": 4, "url": "https://example.com/first"}, 0.01)

        self.assertEqual(1, pipeline_runner.reconcile_due_ranking_tasks())

        job = RankingReconciliationJob.query.filter_by(snapshot_id=self.snapshot.id).first()
        self.assertEqual("completed", job.status)
        self.assertEqual("complete", self.snapshot.status)
        self.assertEqual("found", Ranking.query.filter_by(snapshot_id=self.snapshot.id).one().check_status)
        notes = json.loads(self.snapshot.notes)
        self.assertNotIn("ranking_task_state", notes)
        self.assertEqual("complete", notes["progress"]["ranking_state"])
        self.assertEqual("complete", notes["stage_results"][0]["status"])

    @patch.object(pipeline_runner, "get_ready_keyword_ranking_task_ids", return_value=set())
    def test_reconciliation_marks_provider_timeout_only_after_full_wait_budget(self, _ready_task_ids):
        state = self._pending_ranking_state(
            foreground_wait_until=time_to_iso(-600),
            provider_wait_until=time_to_iso(-1),
        )
        self._save_pending_state(
            state,
            status="partial",
            stage_results=[
                {"name": "rankings", "status": "partial", "optional": True, "duration_seconds": 0, "error": "Still processing"},
            ],
        )
        db.session.add(RankingReconciliationJob(
            snapshot_id=self.snapshot.id,
            client_id=self.client.id,
            status="pending",
            next_poll_at=datetime.datetime.utcnow() - datetime.timedelta(seconds=1),
        ))
        db.session.commit()

        self.assertEqual(1, pipeline_runner.reconcile_due_ranking_tasks())

        job = RankingReconciliationJob.query.filter_by(snapshot_id=self.snapshot.id).first()
        self.assertEqual("expired", job.status)
        self.assertEqual("partial", self.snapshot.status)
        row = Ranking.query.filter_by(snapshot_id=self.snapshot.id).one()
        self.assertEqual("failed", row.check_status)
        self.assertIn("Timed out waiting", row.error_message)
        self.assertEqual("timed_out", json.loads(self.snapshot.notes)["progress"]["ranking_state"])

    def test_stage_results_survive_final_result_note_updates(self):
        self.snapshot.notes = json.dumps({
            "progress": {},
            "stage_results": [{"name": "crawl", "status": "complete", "optional": False}],
        })
        db.session.commit()

        pipeline_runner._update_snapshot_notes(self.snapshot, {"rankings": {"rows": 1}}, status="partial")

        notes = json.loads(self.snapshot.notes)
        self.assertEqual("partial", self.snapshot.status)
        self.assertEqual("crawl", notes["stage_results"][0]["name"])


def time_to_iso(offset_seconds):
    return (datetime.datetime.utcnow() + datetime.timedelta(seconds=offset_seconds)).isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    unittest.main()
