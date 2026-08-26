import unittest
from unittest.mock import Mock, patch

import config
from app import create_app
from app.models import AISetting, User, db
from services import ai_models
from services.ai_models import AIModelValidationError


def _response(*, status_code=200, payload=None, text=""):
    response = Mock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = text
    response.reason = "error" if status_code >= 400 else "OK"
    response.json.return_value = payload if payload is not None else {}
    if status_code >= 400:
        response.raise_for_status.side_effect = ai_models.requests.HTTPError(f"{status_code} error")
    return response


class OpenRouterModelValidationTests(unittest.TestCase):
    def setUp(self):
        self.original_key = config.OPENROUTER_API_KEY
        config.OPENROUTER_API_KEY = "test-key"
        ai_models._catalog_cache = None

    def tearDown(self):
        config.OPENROUTER_API_KEY = self.original_key
        ai_models._catalog_cache = None

    def test_catalog_filters_to_tool_capable_models_and_preserves_legacy_selection(self):
        catalog_response = _response(payload={
            "data": [
                {"id": "provider/tool-model", "name": "Tool model", "context_length": 128000, "supported_parameters": ["tools", "tool_choice"]},
                {"id": "provider/chat-only", "name": "Chat only", "supported_parameters": []},
            ]
        })
        with patch("services.ai_models.requests.get", return_value=catalog_response):
            options, warning = ai_models.model_options_for_selection("legacy/removed-model")

        self.assertIsNone(warning)
        self.assertEqual(options[0], ("provider/tool-model", "Tool model · 128,000 context"))
        self.assertIn(("legacy/removed-model", "legacy/removed-model — saved selection, not available for new choices"), options)

    def test_validation_uses_endpoint_availability_and_copilot_tools_payload(self):
        catalog_response = _response(payload={
            "data": [{"id": "provider/tool-model", "name": "Tool model", "supported_parameters": ["tools", "tool_choice"]}]
        })
        endpoints_response = _response(payload={"data": {"endpoints": [{"provider_name": "example"}]}})
        completion_response = _response(payload={"choices": [{"message": {"role": "assistant", "content": "Compatible"}}]})
        with patch("services.ai_models.requests.get", side_effect=[catalog_response, endpoints_response]) as get, patch(
            "services.ai_models.requests.post", return_value=completion_response
        ) as post:
            ai_models.validate_model_for_copilot("provider/tool-model")

        self.assertEqual(get.call_count, 2)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "provider/tool-model")
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertFalse(payload["parallel_tool_calls"])
        self.assertEqual(payload["tools"][0]["function"]["name"], "model_validation_echo")

    def test_validation_reports_provider_body_for_unroutable_model(self):
        catalog_response = _response(payload={
            "data": [{"id": "provider/tool-model", "name": "Tool model", "supported_parameters": ["tools", "tool_choice"]}]
        })
        endpoints_response = _response(payload={"data": {"endpoints": [{"provider_name": "example"}]}})
        unavailable_response = _response(
            status_code=404,
            payload={"error": {"message": "No endpoints found for provider/tool-model."}},
        )
        with patch("services.ai_models.requests.get", side_effect=[catalog_response, endpoints_response]), patch(
            "services.ai_models.requests.post", return_value=unavailable_response
        ):
            with self.assertRaisesRegex(AIModelValidationError, "No endpoints found"):
                ai_models.validate_model_for_copilot("provider/tool-model")

    def test_validation_rejects_a_model_missing_copilot_capabilities_before_provider_call(self):
        catalog_response = _response(payload={
            "data": [{"id": "provider/chat-only", "name": "Chat only", "supported_parameters": []}]
        })
        with patch("services.ai_models.requests.get", return_value=catalog_response), patch(
            "services.ai_models.requests.post"
        ) as post:
            with self.assertRaisesRegex(AIModelValidationError, "not currently listed"):
                ai_models.validate_model_for_copilot("provider/chat-only")

        post.assert_not_called()


class AdminModelSelectionTests(unittest.TestCase):
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
            self.admin = User(username="admin", password_hash="not-used", role="admin")
            setting = AISetting(model_name="provider/original", system_prompt="Original")
            db.session.add_all([self.admin, setting])
            db.session.commit()
            self.admin_id = self.admin.id
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.admin_id)
            session["_fresh"] = True

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_settings_validates_a_changed_model_before_committing(self):
        with patch("app.routes.admin.validate_model_for_copilot") as validate:
            response = self.client.post("/settings", data={"model_name": "provider/new", "system_prompt": "Updated"})

        self.assertEqual(response.status_code, 302)
        validate.assert_called_once_with("provider/new")
        with self.app.app_context():
            setting = AISetting.query.one()
            self.assertEqual(setting.model_name, "provider/new")
            self.assertEqual(setting.system_prompt, "Updated")

    def test_settings_preserves_current_model_when_validation_fails(self):
        with patch(
            "app.routes.admin.validate_model_for_copilot",
            side_effect=AIModelValidationError("No endpoints found"),
        ):
            response = self.client.post("/settings", data={"model_name": "provider/unavailable", "system_prompt": "Updated"})

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            setting = AISetting.query.one()
            self.assertEqual(setting.model_name, "provider/original")
            self.assertEqual(setting.system_prompt, "Original")

    def test_unchanged_legacy_model_can_be_preserved_while_other_settings_are_updated(self):
        with patch("app.routes.admin.validate_model_for_copilot") as validate:
            response = self.client.post(
                "/settings",
                data={"model_name": "provider/original", "system_prompt": "Prompt only update"},
            )

        self.assertEqual(response.status_code, 302)
        validate.assert_not_called()
        with self.app.app_context():
            setting = AISetting.query.one()
            self.assertEqual(setting.model_name, "provider/original")
            self.assertEqual(setting.system_prompt, "Prompt only update")

    def test_settings_renders_saved_model_when_catalog_is_unavailable(self):
        with patch(
            "app.routes.admin.model_options_for_selection",
            return_value=([("provider/original", "provider/original — saved selection")], "Catalog temporarily unavailable."),
        ):
            response = self.client.get("/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"provider/original", response.data)
        self.assertIn(b"Catalog temporarily unavailable.", response.data)


if __name__ == "__main__":
    unittest.main()
