"""Provider-neutral, server-authorized tools for Copilot and future MCP."""

from dataclasses import dataclass
import inspect
import json
import logging
import time
import uuid


logger = logging.getLogger(__name__)

STANDARD_TOOL_NAMES = (
    "get_ga4_data", "get_gsc_data", "get_rankings", "get_backlinks",
    "get_crawl_issues", "get_competitor_data", "get_project_health",
)

_DATE = {"type": "string", "description": "ISO calendar date, YYYY-MM-DD."}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}
STANDARD_TOOL_CONTRACTS = {
    "get_ga4_data": {"description": "Read stored GA4 daily sessions for this project. Never refreshes GA4.", "input_schema": {"type": "object", "additionalProperties": False, "properties": {"days": {"type": "integer", "minimum": 7, "maximum": 90, "default": 30}, "start_date": _DATE, "end_date": _DATE}}},
    "get_gsc_data": {"description": "Read stored Search Console daily clicks, impressions, CTR and position for this project. Never refreshes GSC.", "input_schema": {"type": "object", "additionalProperties": False, "properties": {"days": {"type": "integer", "minimum": 7, "maximum": 90, "default": 30}, "start_date": _DATE, "end_date": _DATE}}},
    "get_rankings": {"description": "Read stored project keyword rankings and movement. Competitor data is excluded unless requested with the competitor tool.", "input_schema": {"type": "object", "additionalProperties": False, "properties": {"keyword": {"type": "string", "maxLength": 255}, "limit": _LIMIT}}},
    "get_backlinks": {"description": "Read project backlink totals and referring-domain movement from completed audit snapshots.", "input_schema": {"type": "object", "additionalProperties": False, "properties": {"limit": _LIMIT}}},
    "get_crawl_issues": {"description": "Read stored crawl issue groups from the latest completed crawl, with bounded examples.", "input_schema": {"type": "object", "additionalProperties": False, "properties": {"issue_type": {"type": "string", "maxLength": 64}, "limit": _LIMIT}}},
    "get_competitor_data": {"description": "Read stored competitor insight and comparison data for this project only.", "input_schema": {"type": "object", "additionalProperties": False, "properties": {"competitor_id": {"type": "integer", "minimum": 1}, "limit": _LIMIT}}},
    "get_project_health": {"description": "Read the latest persisted, explainable project health score and its components.", "input_schema": {"type": "object", "additionalProperties": False, "properties": {}}},
}


@dataclass(frozen=True)
class ToolContext:
    client_id: int
    user_id: int | None = None
    user_role: str | None = None
    run_id: int | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    handler: object
    input_schema: dict


def _validate_arguments(schema, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unknown = set(arguments) - set(properties)
        if unknown:
            raise ValueError(f"Unsupported tool argument(s): {', '.join(sorted(unknown))}")
    for key, value in arguments.items():
        rule = properties.get(key, {})
        expected = rule.get("type")
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"{key} must be an integer.")
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        if "minimum" in rule and value < rule["minimum"]:
            raise ValueError(f"{key} must be at least {rule['minimum']}.")
        if "maximum" in rule and value > rule["maximum"]:
            raise ValueError(f"{key} must be at most {rule['maximum']}.")
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            raise ValueError(f"{key} is too long.")


class ToolRegistry:
    """One stable contract for OpenRouter, Flask, and a future MCP adapter."""

    def __init__(self, *, max_history=100):
        self._tools, self._history = {}, []
        self.max_history = max(1, int(max_history))

    def register(self, name, handler, *, description="", input_schema=None):
        if not name or not callable(handler):
            raise ValueError("A tool name and callable handler are required.")
        self._tools[name] = ToolDefinition(name, description, handler, input_schema or {"type": "object", "properties": {}})
        return self._tools[name]

    def register_standard_tools(self, handlers):
        for name in STANDARD_TOOL_NAMES:
            if handler := handlers.get(name):
                contract = STANDARD_TOOL_CONTRACTS[name]
                self.register(name, handler, description=contract["description"], input_schema=contract["input_schema"])
        return self

    def get(self, name):
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def definitions(self):
        return tuple(self._tools.values())

    def openai_definitions(self):
        return [{"type": "function", "function": {"name": item.name, "description": item.description, "parameters": item.input_schema}} for item in self.definitions()]

    def invoke(self, name, arguments=None, *, context=None):
        definition, arguments = self.get(name), (arguments or {})
        _validate_arguments(definition.input_schema, arguments)
        invocation_id, started = uuid.uuid4().hex, time.monotonic()
        try:
            signature = inspect.signature(definition.handler)
            if "context" in signature.parameters:
                value = definition.handler(context=context, **arguments)
            else:  # Compatibility for the initial injected-handler registry tests.
                value = definition.handler(**arguments)
            status, error = "success", None
        except Exception as exc:
            value, status, error = None, "failed", str(exc)
        record = {"invocation_id": invocation_id, "tool_name": name, "status": status, "duration_ms": round((time.monotonic() - started) * 1000, 2), "arguments": arguments, "context": {"client_id": getattr(context, "client_id", None)}, "error": error}
        self._history.append(record)
        del self._history[:-self.max_history]
        logger.info("tool_execution=%s", json.dumps(record, default=str, sort_keys=True))
        if error:
            raise RuntimeError(f"Tool {name} failed: {error}")
        return value, record

    def history(self):
        return tuple(self._history)
