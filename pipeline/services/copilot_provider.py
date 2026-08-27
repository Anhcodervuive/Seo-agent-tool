"""OpenRouter adapter that preserves the metadata needed by the agent loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

import config


class CopilotProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CopilotCompletion:
    """One normalized Chat Completions result, independent of model provider."""

    message: dict[str, Any]
    finish_reason: str | None
    routed_model: str | None
    provider: str | None
    usage: dict[str, Any]


class OpenRouterCopilotProvider:
    def complete(self, *, model_name, messages, tools=None):
        if not config.OPENROUTER_API_KEY:
            raise CopilotProviderError("OpenRouter is not configured. Add OPENROUTER_API_KEY before using Copilot.")
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.2,
            "provider": {"require_parameters": True},
        }
        if tools:
            payload.update({
                "tools": tools,
                "tool_choice": "auto",
            })
        try:
            response = requests.post(
                config.OPENROUTER_URL,
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            response.raise_for_status()
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise CopilotProviderError("Copilot provider returned an invalid assistant message.")
        except (requests.RequestException, IndexError, KeyError, TypeError, ValueError) as exc:
            raise CopilotProviderError(f"Copilot provider request failed: {exc}") from exc
        return CopilotCompletion(
            message=message,
            finish_reason=choice.get("finish_reason"),
            routed_model=body.get("model"),
            provider=body.get("provider"),
            usage=body.get("usage") if isinstance(body.get("usage"), dict) else {},
        )
