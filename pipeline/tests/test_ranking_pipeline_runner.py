import json
import unittest
from unittest.mock import patch

from flask import Flask

from app.models import Client, Keyword, Ranking, Snapshot, db
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
        get_task_result.side_effect = [
            ({"status": "found", "position": 4, "url": "https://example.com/first"}, 0.01),
            ({"status": "not_found", "position": None, "url": None}, 0.01),
        ]

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


if __name__ == "__main__":
    unittest.main()
