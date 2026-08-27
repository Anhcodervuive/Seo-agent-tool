# Copilot failure feedback and retry

**Status:** delivered on 2026-08-27.

## Purpose and user-facing result

Previously, a Copilot run that failed in the worker disappeared from the active
run list. The user message remained visible, but no assistant response
explained what happened. Copilot now writes a durable, assistant-styled failure
event into the same project conversation. It explains that the answer was not
completed, confirms that no project data was changed, and offers a **Try again**
action when it is safe to retry.

The message remains after refreshing the page and while paging back through
conversation history. It is deliberately a `system` conversation message, so it
is visible to people but excluded from the user/assistant history sent to the
next model request.

## Failure handling flow

```text
Worker exception
  -> retain raw diagnostic on copilot_runs.error_message
  -> classify the failure for the user
  -> save a system failure message with a safe code and run ID
  -> state API returns the message and retry metadata
  -> UI replaces the typing state with a visible error bubble
```

The public message never exposes the raw provider response, request payload, or
API key. Current classifications include unavailable model/provider,
configuration missing, timeout, response safety limit, and a safe temporary
error fallback. The reference format, such as `COPILOT-MODEL-UNAVAILABLE`, lets
support correlate the message with the durable run record.

## Retry behaviour

`POST /project/<client_id>/copilot/runs/<run_id>/retry` accepts only a failed
run belonging to the same permitted user (or an admin). It creates one new
pending run pointing to the original user message; it does not duplicate the
question in history. Retry is rejected while that conversation already has a
pending or running run.

The normal worker claims and executes the new run, so all existing model,
tool, timeout, and audit safeguards still apply.

## Data and deployment

This uses the existing `copilot_messages.citations` JSON field to persist safe
failure metadata, and the existing `copilot_runs.error_message` field for the
private raw diagnostic. No schema migration or data rewrite is required.
Deploy the normal `web` and `worker` services together: web serves state/retry
API and chat UI; worker creates the failure event.

## Verification

Regression coverage verifies that an OpenRouter-like 404 produces a durable,
sanitized failure message, that the state API serializes its retry metadata, and
that retry queues a new run without duplicating the user message or allowing a
second active retry.

## Delivery

- `0100c43` — `Show Copilot failures in chat`.
