"""Provider-neutral tool registry for Week 3 AI and MCP adapters."""

from dataclasses import dataclass
import json
import logging
import time
import uuid


logger = logging.getLogger(__name__)

STANDARD_TOOL_NAMES = (
    "get_ga4_data",
    "get_gsc_data",
    "get_rankings",
    "get_backlinks",
    "get_crawl_issues",
    "get_competitor_data",
)

STANDARD_TOOL_CONTRACTS = {
    "get_ga4_data": {
        "description": "Read cached or refreshed GA4 metrics for the current project.",
        "input_schema": {"type": "object", "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"}}},
    },
    "get_gsc_data": {
        "description": "Read cached or refreshed Google Search Console metrics.",
        "input_schema": {"type": "object", "properties": {"view": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}},
    },
    "get_rankings": {
        "description": "Read tracked keyword and competitor ranking history.",
        "input_schema": {"type": "object", "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer"}}},
    },
    "get_backlinks": {
        "description": "Read backlink totals, referring domains and recent movement.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    "get_crawl_issues": {
        "description": "Read technical crawl issues and page-level evidence.",
        "input_schema": {"type": "object", "properties": {"severity": {"type": "string"}, "limit": {"type": "integer"}}},
    },
    "get_competitor_data": {
        "description": "Read competitor visibility, ranking and backlink comparisons.",
        "input_schema": {"type": "object", "properties": {"competitor_id": {"type": "integer"}}},
    },
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    handler: object
    input_schema: dict


class ToolRegistry:
    """Register and invoke tools with one consistent execution contract."""

    def __init__(self, *, max_history=100):
        self._tools = {}
        self._history = []
        self.max_history = max(1, int(max_history))

    def register(self, name, handler, *, description="", input_schema=None):
        if not name or not callable(handler):
            raise ValueError("A tool name and callable handler are required.")
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            handler=handler,
            input_schema=input_schema or {"type": "object", "properties": {}},
        )
        return self._tools[name]

    def register_standard_tools(self, handlers):
        """Register the stable Week 3 contracts with injected handlers.

        The handlers are intentionally injected so OpenRouter, MCP and Flask
        can share the contract without sharing transport or app globals.
        """
        for name in STANDARD_TOOL_NAMES:
            handler = handlers.get(name)
            if handler is None:
                continue
            contract = STANDARD_TOOL_CONTRACTS[name]
            self.register(
                name,
                handler,
                description=contract["description"],
                input_schema=contract["input_schema"],
            )
        return self

    def get(self, name):
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def definitions(self):
        return tuple(self._tools.values())

    def invoke(self, name, arguments=None, *, context=None):
        definition = self.get(name)
        invocation_id = uuid.uuid4().hex
        started = time.monotonic()
        arguments = arguments or {}
        try:
            value = definition.handler(**arguments)
            status = "success"
            error = None
        except Exception as exc:
            value = None
            status = "failed"
            error = str(exc)
        record = {
            "invocation_id": invocation_id,
            "tool_name": name,
            "status": status,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "arguments": arguments,
            "context": context or {},
            "error": error,
        }
        self._history.append(record)
        del self._history[:-self.max_history]
        logger.info("tool_execution=%s", json.dumps(record, default=str, sort_keys=True))
        if error:
            raise RuntimeError(f"Tool {name} failed: {error}")
        return value

    def history(self):
        return tuple(self._history)
