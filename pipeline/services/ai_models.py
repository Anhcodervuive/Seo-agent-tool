"""OpenRouter-backed model discovery and compatibility checks for SEO Copilot."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

import requests

import config


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_MODEL_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"
CATALOG_CACHE_SECONDS = 15 * 60
REQUEST_TIMEOUT_SECONDS = 20


class AIModelValidationError(RuntimeError):
    """A model cannot safely be selected for the application's Copilot flow."""


@dataclass(frozen=True)
class ModelCatalog:
    options: list[tuple[str, str]]
    model_ids: frozenset[str]
    warning: str | None = None


_catalog_cache: tuple[float, ModelCatalog] | None = None


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.OPENROUTER_API_KEY:
        headers["Authorization"] = f"Bearer {config.OPENROUTER_API_KEY}"
    return headers


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if body.get("message"):
            return str(body["message"])
    return (response.text or response.reason or "Unknown provider error").strip()[:500]


def _catalog_from_payload(payload: dict[str, Any]) -> ModelCatalog:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise AIModelValidationError("OpenRouter returned an invalid model catalog response.")

    options: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        supported = set(row.get("supported_parameters") or [])
        if not isinstance(model_id, str) or not {"tools", "tool_choice"}.issubset(supported):
            continue
        name = row.get("name") or model_id
        context = row.get("context_length")
        context_label = f" · {context:,} context" if isinstance(context, int) and context else ""
        options.append((model_id, f"{name}{context_label}"))

    options.sort(key=lambda option: option[1].casefold())
    return ModelCatalog(options=options, model_ids=frozenset(value for value, _ in options))


def get_copilot_model_catalog(*, force_refresh: bool = False) -> ModelCatalog:
    """Return models declared by OpenRouter as supporting the Copilot tool profile."""
    global _catalog_cache
    now = monotonic()
    if not force_refresh and _catalog_cache and now - _catalog_cache[0] < CATALOG_CACHE_SECONDS:
        return _catalog_cache[1]

    try:
        response = requests.get(
            OPENROUTER_MODELS_URL,
            headers=_headers(),
            params={"supported_parameters": "tools", "output_modalities": "text"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        catalog = _catalog_from_payload(response.json())
    except (requests.RequestException, ValueError, AIModelValidationError) as exc:
        if _catalog_cache:
            cached = _catalog_cache[1]
            return ModelCatalog(
                options=cached.options,
                model_ids=cached.model_ids,
                warning="Could not refresh the OpenRouter catalog; showing the last known tool-capable models.",
            )
        return ModelCatalog(
            options=[],
            model_ids=frozenset(),
            warning=f"Could not load the OpenRouter model catalog: {exc}",
        )

    _catalog_cache = (now, catalog)
    return catalog


def model_options_for_selection(*selected_models: str | None) -> tuple[list[tuple[str, str]], str | None]:
    """Return provider catalog options while preserving legacy saved values visibly."""
    catalog = get_copilot_model_catalog()
    options = list(catalog.options)
    known_models = set(catalog.model_ids)
    for model_name in selected_models:
        if model_name and model_name not in known_models:
            options.append((model_name, f"{model_name} — saved selection, not available for new choices"))
            known_models.add(model_name)
    return options, catalog.warning


def _ensure_listed_for_copilot(model_name: str) -> None:
    catalog = get_copilot_model_catalog(force_refresh=True)
    if catalog.warning:
        raise AIModelValidationError("OpenRouter's model catalog is unavailable. Try again before changing the model.")
    if model_name not in catalog.model_ids:
        raise AIModelValidationError(
            f"{model_name} is not currently listed by OpenRouter as supporting Copilot tool calling."
        )


def validate_model_for_copilot(model_name: str) -> None:
    """Verify routing and the exact tools payload used by SEO Copilot before saving a model."""
    model_name = (model_name or "").strip()
    if not model_name:
        return
    if not config.OPENROUTER_API_KEY:
        raise AIModelValidationError("OpenRouter is not configured. Add OPENROUTER_API_KEY before choosing a model.")

    _ensure_listed_for_copilot(model_name)
    try:
        endpoint_response = requests.get(
            OPENROUTER_MODEL_ENDPOINTS_URL.format(model=model_name),
            headers=_headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        endpoint_response.raise_for_status()
        endpoint_payload = endpoint_response.json().get("data", {})
        if not endpoint_payload.get("endpoints"):
            raise AIModelValidationError(f"No OpenRouter endpoints are currently available for {model_name}.")

        response = requests.post(
            config.OPENROUTER_URL,
            headers=_headers(),
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "You are a model compatibility check."},
                    {"role": "user", "content": "Confirm that you can respond while tools are available."},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "model_validation_echo",
                            "description": "Returns a fixed confirmation for the compatibility check.",
                            "parameters": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                                "required": ["value"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "temperature": 0,
                "max_tokens": 256,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise AIModelValidationError(
                f"OpenRouter could not run {model_name}: {_error_message(response)}"
            )
        message = response.json()["choices"][0]["message"]
        if not isinstance(message, dict):
            raise AIModelValidationError(f"{model_name} returned an invalid Copilot response during validation.")
    except AIModelValidationError:
        raise
    except (requests.RequestException, AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise AIModelValidationError(f"Could not validate {model_name}: {exc}") from exc
