# Reliable Copilot tool orchestration

**Status:** delivered on 2026-08-27.

## Purpose and user-facing result

SEO Copilot uses models through OpenRouter to select read-only project-data
tools. Previously, its safety limit counted every model request and stopped
after four requests. A capable model could use all four requests for legitimate
research, then be denied the next request needed to summarize the collected
evidence. The chat run was marked failed even though every tool invocation had
succeeded.

Copilot now separates **research** from **answering**. It permits up to four
tool-research rounds and six total tool calls, then gives the model one mandatory
tool-free finalization request. This guarantees a model that has spent its
research budget can still answer from the evidence already collected.

The system prompt also asks models to answer greetings and other small-talk
without calling project-data tools.

## Data flow

```text
User message -> model request with SEO tools
  -> tool call(s)? -> execute read-only tools and append results
  -> repeat for at most 4 research rounds / 6 calls
  -> final request without a tools array
  -> persist assistant answer and citations
```

If a model answers before the research budget is reached, its direct answer is
persisted immediately. If it asks for more than six calls, those additional
calls are not executed; the finalizer answers from already collected data and
must identify any insufficiency plainly. A 180-second wall-clock limit remains
as the outer safety boundary.

`OpenRouterCopilotProvider` now returns routing metadata (`finish_reason`,
routed model, provider, and token usage) to the agent. The worker logs compact
`copilot.model_turn` JSON events with the run ID, research round, requested tool
names, finish reason, routing metadata, usage, and whether the turn was the
tool-free finalizer. These logs intentionally omit API keys and message text.

## Model and provider safeguards

- Tool-enabled runtime requests send OpenRouter
  `provider.require_parameters: true`, so a provider fallback must support all
  requested tool parameters rather than silently degrading the request. The
  request deliberately omits `parallel_tool_calls`: OpenRouter's live routing
  check showed that Claude Opus 5 has available tool-capable endpoints, but no
  endpoint that advertises that optional parameter. Tool invocations are still
  executed safely one at a time by the application.
- The finalizer omits the `tools` and `tool_choice` fields completely. It
  therefore works across models without relying on
  model-specific support for `tool_choice: none`.
- Saving a changed model now verifies the full lifecycle: catalogue capability,
  active endpoint, one forced synthetic tool call, a returned tool result, and
  a non-tool final answer. A failed check preserves the existing setting.

This follows the client-tool loop described by Anthropic's
[tool-use guide](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)
and OpenRouter's [tool-calling guide](https://openrouter.ai/docs/guides/features/tool-calling).
OpenRouter's [provider routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection)
defines the `require_parameters` safeguard.

## Configuration, deployment, and limitations

- Uses the existing `OPENROUTER_API_KEY` and `OPENROUTER_URL`; no migration,
  database mutation, or model setting migration is required.
- Rebuild and recreate both `web` and `worker` through the normal Compose
  deployment because the worker executes the agent loop and the web service
  validates newly selected models.
- A changed model now makes two small live validation completions (each capped
  at 512 output tokens), so validation incurs a modest OpenRouter charge.
- Provider availability and model behavior can still change after validation.
  The lifecycle probe verifies the concrete integration path but is not a
  substitute for product-level evaluation of answer quality.

## Verification

Local checks completed:

- Focused model/provider/Copilot tests: 17 passed.
- Full suite: `python -m unittest discover -s tests -p "test_*.py" -v` — 123
  passed.
- `python -m compileall -q app services tests migrations manage.py run.py`,
  `docker compose config --quiet`, and `git diff --check` passed.

The regression suite includes a four-round research model double: it calls
rankings, GSC, backlinks, and project health in four successive turns, then
confirms that Copilot makes a fifth request without tools and saves the final
answer instead of failing.

## Delivery

- Implementation commit: `94f6f10` — `Harden Copilot tool orchestration`.
- Routing compatibility follow-up: `b55b79d` — removes the unsupported
  `parallel_tool_calls: false` request parameter while preserving strict
  OpenRouter parameter routing.
- Key code: `pipeline/services/copilot_agent.py`,
  `pipeline/services/copilot_provider.py`, and `pipeline/services/ai_models.py`.
