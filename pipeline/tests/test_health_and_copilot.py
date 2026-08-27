import unittest
from datetime import date, datetime, timedelta

import config
from sqlalchemy import inspect
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
    User,
    db,
)
from services.copilot_agent import FINALIZATION_INSTRUCTION, _conversation_messages, run_copilot_run
from services.copilot_history import DEFAULT_COPILOT_MESSAGE_PAGE_SIZE
from services.health import persist_health_score
from services.tool_registry import ToolRegistry


class _FakeProvider:
    def complete(self, **kwargs):
        if any(message.get("role") == "tool" for message in kwargs["messages"]):
            return {"content": "The stored health score is 77.", "tool_calls": []}
        return {"content": "", "tool_calls": [{"id": "call_health", "function": {"name": "get_project_health", "arguments": "{}"}}]}


class _FourResearchRoundsProvider:
    """Emulates a thorough model such as Opus that researches four times first."""

    def __init__(self):
        self.requests = []
        self.tool_names = ["get_rankings", "get_gsc_data", "get_backlinks", "get_project_health"]

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs["tools"] is None:
            return {"content": "Here is the final SEO summary.", "tool_calls": [], "finish_reason": "stop"}
        tool_name = self.tool_names[len(self.requests) - 1]
        return {
            "content": "",
            "finish_reason": "tool_calls",
            "tool_calls": [{
                "id": f"call_{tool_name}",
                "function": {"name": tool_name, "arguments": "{}"},
            }],
        }


class _UnavailableModelProvider:
    def complete(self, **kwargs):
        raise RuntimeError("Copilot provider request failed: 404 Client Error: Not Found")


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
            self.admin = User(username="admin", password_hash="not-used", role="admin")
            db.session.add_all([self.client, self.admin])
            db.session.commit()
            self.client_id = self.client.id
            self.admin_id = self.admin.id
        self.http_client = self.app.test_client()
        with self.http_client.session_transaction() as session:
            session["_user_id"] = str(self.admin_id)
            session["_fresh"] = True

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

    def test_agent_reserves_a_tool_free_finalization_turn_after_four_research_rounds(self):
        with self.app.app_context():
            conversation = CopilotConversation(client_id=self.client_id, title="Research")
            db.session.add(conversation)
            db.session.flush()
            message = CopilotMessage(conversation_id=conversation.id, role="user", content="Give me an SEO overview.")
            db.session.add(message)
            db.session.flush()
            run = CopilotRun(conversation_id=conversation.id, client_id=self.client_id, user_message_id=message.id)
            db.session.add(run)
            db.session.commit()

            registry = ToolRegistry()
            for tool_name in ("get_rankings", "get_gsc_data", "get_backlinks", "get_project_health"):
                registry.register(
                    tool_name,
                    lambda *, context, name=tool_name: {
                        "data": {"tool": name},
                        "meta": {"source": "test"},
                        "citations": [{"type": "test", "tool": name}],
                    },
                    input_schema={"type": "object", "additionalProperties": False, "properties": {}},
                )
            provider = _FourResearchRoundsProvider()
            result = run_copilot_run(run.id, provider=provider, registry=registry)

            self.assertIsNotNone(result, db.session.get(CopilotRun, run.id).error_message)
            self.assertEqual(result.content, "Here is the final SEO summary.")
            self.assertEqual(len(provider.requests), 5)
            self.assertTrue(all(request["tools"] for request in provider.requests[:4]))
            self.assertIsNone(provider.requests[4]["tools"])
            self.assertEqual(provider.requests[4]["messages"][-1], {
                "role": "user", "content": FINALIZATION_INSTRUCTION,
            })
            refreshed = db.session.get(CopilotRun, run.id)
            self.assertEqual(refreshed.status, "completed")
            self.assertEqual(len(refreshed.invocations), 4)

    def test_agent_persists_a_user_safe_failure_message_for_an_unavailable_model(self):
        with self.app.app_context():
            conversation = CopilotConversation(client_id=self.client_id, created_by_user_id=self.admin_id, title="Failure")
            db.session.add(conversation)
            db.session.flush()
            user_message = CopilotMessage(conversation_id=conversation.id, role="user", content="What should I fix?")
            db.session.add(user_message)
            db.session.flush()
            run = CopilotRun(
                conversation_id=conversation.id,
                client_id=self.client_id,
                requested_by_user_id=self.admin_id,
                user_message_id=user_message.id,
            )
            db.session.add(run)
            db.session.commit()

            self.assertIsNone(run_copilot_run(run.id, provider=_UnavailableModelProvider(), registry=ToolRegistry()))
            failed_run = db.session.get(CopilotRun, run.id)
            failure_message = CopilotMessage.query.filter_by(conversation_id=conversation.id, role="system").one()
            self.assertEqual(failed_run.status, "failed")
            self.assertIn("404", failed_run.error_message)
            self.assertIn("selected AI model is not available", failure_message.content)
            self.assertNotIn("404", failure_message.content)
            self.assertEqual(failure_message.citations[0]["code"], "COPILOT-MODEL-UNAVAILABLE")
            self.assertEqual(failure_message.citations[0]["run_id"], run.id)
            self.assertEqual(_conversation_messages(conversation), [{
                "role": "user", "content": "What should I fix?",
            }])

        state = self.http_client.get(f"/project/{self.client_id}/copilot/state")
        self.assertEqual(state.status_code, 200)
        failure = state.get_json()["messages"][-1]
        self.assertEqual(failure["role"], "system")
        self.assertEqual(failure["failure"], {
            "code": "COPILOT-MODEL-UNAVAILABLE",
            "run_id": run.id,
            "retryable": True,
        })

    def test_failed_copilot_run_can_be_retried_without_duplicating_the_user_message(self):
        with self.app.app_context():
            conversation = CopilotConversation(client_id=self.client_id, created_by_user_id=self.admin_id, title="Retry")
            db.session.add(conversation)
            db.session.flush()
            user_message = CopilotMessage(conversation_id=conversation.id, role="user", content="Check this project")
            db.session.add(user_message)
            db.session.flush()
            failed_run = CopilotRun(
                conversation_id=conversation.id,
                client_id=self.client_id,
                requested_by_user_id=self.admin_id,
                user_message_id=user_message.id,
                status="failed",
                error_message="provider unavailable",
            )
            db.session.add(failed_run)
            db.session.commit()
            failed_run_id = failed_run.id
            user_message_id = user_message.id

        response = self.http_client.post(f"/project/{self.client_id}/copilot/runs/{failed_run_id}/retry")
        self.assertEqual(response.status_code, 202)
        retry_run_id = response.get_json()["run"]["id"]
        with self.app.app_context():
            retry_run = db.session.get(CopilotRun, retry_run_id)
            self.assertEqual(retry_run.status, "pending")
            self.assertEqual(retry_run.user_message_id, user_message_id)
            self.assertEqual(CopilotMessage.query.filter_by(conversation_id=retry_run.conversation_id).count(), 1)
            self.assertEqual(CopilotRun.query.filter_by(conversation_id=retry_run.conversation_id).count(), 2)

        duplicate_retry = self.http_client.post(f"/project/{self.client_id}/copilot/runs/{failed_run_id}/retry")
        self.assertEqual(duplicate_retry.status_code, 409)

    def test_copilot_state_uses_latest_cursor_window_and_delta_messages(self):
        with self.app.app_context():
            conversation = CopilotConversation(
                client_id=self.client_id,
                created_by_user_id=self.admin_id,
                title="Long conversation",
            )
            db.session.add(conversation)
            db.session.flush()
            db.session.add_all([
                CopilotMessage(
                    conversation_id=conversation.id,
                    role="user" if index % 2 else "assistant",
                    content=f"message-{index:02d}",
                )
                for index in range(1, 96)
            ])
            db.session.commit()

        initial = self.http_client.get(f"/project/{self.client_id}/copilot/state")
        self.assertEqual(initial.status_code, 200)
        initial_body = initial.get_json()
        self.assertEqual(len(initial_body["messages"]), DEFAULT_COPILOT_MESSAGE_PAGE_SIZE)
        self.assertEqual(
            [row["content"] for row in initial_body["messages"]],
            [f"message-{index:02d}" for index in range(66, 96)],
        )
        self.assertTrue(initial_body["page"]["has_older"])
        self.assertEqual(initial_body["page"]["mode"], "latest")
        first_latest_id = initial_body["page"]["oldest_message_id"]
        last_latest_id = initial_body["page"]["newest_message_id"]

        older = self.http_client.get(
            f"/project/{self.client_id}/copilot/state",
            query_string={"before_message_id": first_latest_id},
        )
        self.assertEqual(older.status_code, 200)
        older_body = older.get_json()
        self.assertEqual(
            [row["content"] for row in older_body["messages"]],
            [f"message-{index:02d}" for index in range(36, 66)],
        )
        self.assertTrue(older_body["page"]["has_older"])

        with self.app.app_context():
            conversation = db.session.get(CopilotConversation, initial_body["conversation"]["id"])
            db.session.add_all([
                CopilotMessage(conversation_id=conversation.id, role="user", content="message-96"),
                CopilotMessage(conversation_id=conversation.id, role="assistant", content="message-97"),
            ])
            db.session.commit()

        delta = self.http_client.get(
            f"/project/{self.client_id}/copilot/state",
            query_string={"after_message_id": last_latest_id},
        )
        self.assertEqual(delta.status_code, 200)
        delta_body = delta.get_json()
        self.assertEqual([row["content"] for row in delta_body["messages"]], ["message-96", "message-97"])
        self.assertEqual(delta_body["page"]["mode"], "after")
        self.assertFalse(delta_body["page"]["has_newer"])

    def test_copilot_state_rejects_ambiguous_or_unbounded_cursor_requests(self):
        response = self.http_client.get(
            f"/project/{self.client_id}/copilot/state",
            query_string={"before_message_id": 1, "after_message_id": 2},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("either before_message_id or after_message_id", response.get_json()["error"])

        response = self.http_client.get(
            f"/project/{self.client_id}/copilot/state",
            query_string={"limit": 51},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("must not exceed 50", response.get_json()["error"])

    def test_copilot_message_cursor_index_is_declared(self):
        with self.app.app_context():
            index_names = {index["name"] for index in inspect(db.engine).get_indexes("copilot_messages")}
        self.assertIn("ix_copilot_messages_conversation_id_id", index_names)


if __name__ == "__main__":
    unittest.main()
