# OpenRouter model selection validation for SEO Copilot

**Status:** delivered on 2026-08-26.

## Purpose and user-facing result

SEO Copilot previously offered a fixed list of model IDs. A model could be
removed, renamed, or no longer routed by OpenRouter after that list was
released, then be saved to a project and make every Copilot run fail at runtime
with a provider error such as HTTP 404.

The Admin **AI Settings** page and the project-level AI override now use the
live OpenRouter model catalogue. The application only offers models declared as
supporting the tool-calling capabilities that Copilot needs. Before a *changed*
model is persisted, it performs a real, small compatibility request against
OpenRouter. A failed validation leaves the current global/project setting
untouched and shows the provider's actionable error in the form.

This deliberately does **not** silently replace a client's existing model. A
saved legacy model remains visible in the select control, marked as not
available for new choices, so an admin can deliberately choose and validate a
replacement.

## How an admin uses it

1. Open **Admin → AI Settings** to change the global default, or open a project
   and use **AI model override** to set that project's explicit model.
2. Choose a model from the provider-backed list and save.
3. The application accepts the change only if the provider catalogue, active
   endpoint check, and a tool-enabled completion probe succeed.
4. If validation fails, read the on-page error, choose another available model,
   and save again. The formerly configured model remains active until a
   replacement passes.

Changing only the system prompt while retaining an older saved model is allowed;
that is not an implicit model migration.

## Data flow and source of truth

```text
Admin form
  -> Flask admin route
  -> OpenRouter GET /api/v1/models (catalogue: tools + tool_choice)
  -> OpenRouter GET /api/v1/models/{model}/endpoints (active routing)
  -> OpenRouter POST /api/v1/chat/completions (Copilot-shaped tools probe)
  -> pass: update ai_settings or project_ai_settings
  -> fail: flash error; do not commit a model change
```

The global setting is stored in `ai_settings`; a project override is stored in
`project_ai_settings`. At Copilot-run time the existing effective-settings logic
continues to choose the project override first, otherwise the global default.
The validation layer never rewrites either table without an explicit admin form
submission.

The model catalogue response is cached in-process for 15 minutes to avoid
calling OpenRouter for every settings-page view. A failed refresh uses the last
known catalogue if available and displays a warning. If no catalogue is
available, an admin cannot save a new model choice, while existing selections
remain visible and unchanged.

The integration follows OpenRouter's documented [Models API](https://openrouter.ai/docs/guides/overview/models),
[Endpoints API](https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints),
and [tool-calling contract](https://openrouter.ai/docs/guides/features/tool-calling).

## Configuration, deployment, and cost

- Uses the existing `OPENROUTER_API_KEY` and `OPENROUTER_URL`; no new secrets or
  database migration are required.
- The server gives each provider call a 20-second timeout. The completion probe
  is intentionally short (`max_tokens: 256`) and does not execute any model
  tool call; it only verifies that OpenRouter accepts Copilot's tool schema and
  returns an assistant message.
- Rebuild/recreate the application services through the normal Docker Compose
  deployment process so the web service receives the new code. No production
  database changes are required.

## Verification and limits

Automated verification completed locally:

- `python -m unittest tests.test_ai_models -v` — 8 tests passed.
- `python -m unittest discover -s tests -p "test_*.py" -v` — 119 tests passed.
- `python -m compileall -q app services run.py manage.py` and `git diff --check`
  passed.

The focused tests cover capability filtering, stale-option preservation,
endpoint availability, provider 404 detail, Copilot tools payload, validation
before commit, failed-validation rollback behavior, and settings-page rendering
when the catalogue is unavailable.

Provider availability can change after a successful validation, so no check can
guarantee a model will remain routable forever. Normal Copilot run errors remain
recorded in `copilot_runs` for diagnosis. The validation probe also incurs a
small OpenRouter usage charge whenever an admin changes a model.

## Delivery

- Implementation commit: `24048a7` — `Validate OpenRouter model choices before saving`.
- Key implementation files: `pipeline/services/ai_models.py` and
  `pipeline/app/routes/admin.py`.
