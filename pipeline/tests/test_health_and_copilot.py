import unittest
from datetime import date, datetime, timedelta

import config
from app import create_app
from app.models import (
    BacklinkHistory,
    Client,
    CopilotConversation,
    CopilotMessage,
    CopilotRun,
    CrawlIssue,
    CrawlPage,
    Ga4DailyMetric,
    GscDailyMetric,
    Ranking,
    Snapshot,
    db,
)
from services.copilot_agent import run_copilot_run
from services.health import persist_health_score
from services.tool_registry import ToolRegistry


class _FakeProvider:
    def complete(self, **kwargs):
        if any(message.get("role") == "tool" for message in kwargs["messages"]):
            return {"content": "The stored health score is 77.", "tool_calls": []}
        return {"content": "", "tool_calls": [{"id": "call_health", "function": {"name": "get_project_health", "arguments": "{}"}}]}


class HealthAndCopilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_uri = config.SQLALCHEMY_DATABASE_URI
        config.SQLALCHEMY_DATABASE_URI = "sqlite://"
        cls.app = create_app()

    @classmethod
    def tearDownClass(cls):
        config.SQLALCHEMY_DATABASE_URI = cls.original_uri

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            self.client = Client(name="Example", domain="example.test")
            db.session.add(self.client)
            db.session.commit()
            self.client_id = self.client.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_health_score_excludes_competitor_rankings_and_persists_components(self):
        with self.app.app_context():
            snapshot = Snapshot(client_id=self.client_id, status="complete", created_at=datetime.utcnow())
            db.session.add(snapshot)
            db.session.flush()
            db.session.add(CrawlPage(snapshot_id=snapshot.id, url="https://example.test/"))
            db.session.add(CrawlIssue(snapshot_id=snapshot.id, issue="Missing title", issue_type="warning"))
            db.session.add_all([
                Ranking(snapshot_id=snapshot.id, keyword="seo", position=8, check_status="found"),
                Ranking(snapshot_id=snapshot.id, competitor_id=999, keyword="seo", position=90, check_status="found"),
                BacklinkHistory(snapshot_id=snapshot.id, referring_domains=10, total_backlinks=20),
            ])
            for offset in range(60):
                metric_date = date.today() - timedelta(days=offset)
                db.session.add(Ga4DailyMetric(client_id=self.client_id, metric_date=metric_date, sessions=100 + offset))
                db.session.add(GscDailyMetric(client_id=self.client_id, metric_date=metric_date, clicks=10 + offset, impressions=100 + offset))
            db.session.commit()
            record = persist_health_score(snapshot)
            self.assertIsNotNone(record)
            self.assertEqual(record.algorithm_version, "v2")
            self.assertEqual(record.components["keywords"]["metrics"]["tracked"], 1)
            self.assertEqual(record.components["keywords"]["metrics"]["average_position"], 8.0)
            self.assertIn("organic", record.components)

    def test_agent_persists_tool_audit_trail_and_server_context(self):
        with self.app.app_context():
            conversation = CopilotConversation(client_id=self.client_id, title="Health")
            db.session.add(conversation)
            db.session.flush()
            message = CopilotMessage(conversation_id=conversation.id, role="user", content="How is health?")
            db.session.add(message)
            db.session.flush()
            run = CopilotRun(conversation_id=conversation.id, client_id=self.client_id, user_message_id=message.id)
            db.session.add(run)
            db.session.commit()

            seen = []
            def health_tool(*, context):
                seen.append(context.client_id)
                return {"data": {"score": 77}, "meta": {"source": "test"}, "citations": [{"type": "snapshot", "snapshot_id": 1}]}
            registry = ToolRegistry()
            registry.register("get_project_health", health_tool, input_schema={"type": "object", "additionalProperties": False, "properties": {}})
            result = run_copilot_run(run.id, provider=_FakeProvider(), registry=registry)
            self.assertIsNotNone(result, db.session.get(CopilotRun, run.id).error_message)
            self.assertEqual(result.content, "The stored health score is 77.")
            self.assertEqual(seen, [self.client_id])
            refreshed = db.session.get(CopilotRun, run.id)
            self.assertEqual(refreshed.status, "completed")
            self.assertEqual(len(refreshed.invocations), 1)


if __name__ == "__main__":
    unittest.main()
