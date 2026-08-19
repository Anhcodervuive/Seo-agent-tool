"""Minimal OpenRouter function-calling adapter, isolated from agent logic."""

import requests

import config


class CopilotProviderError(RuntimeError):
    pass


class OpenRouterCopilotProvider:
    def complete(self, *, model_name, messages, tools):
        if not config.OPENROUTER_API_KEY:
            raise CopilotProviderError("OpenRouter is not configured. Add OPENROUTER_API_KEY before using Copilot.")
        payload = {
            "model": model_name,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "temperature": 0.2,
        }
        try:
            response = requests.post(
                config.OPENROUTER_URL,
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise CopilotProviderError(f"Copilot provider request failed: {exc}") from exc
        return message
