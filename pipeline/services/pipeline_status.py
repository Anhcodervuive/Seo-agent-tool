"""Consistent snapshot progress and stage-result bookkeeping."""

import json


def load_notes(raw_notes):
    try:
        value = json.loads(raw_notes) if raw_notes else {}
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def stage_summary(stage_results):
    """Return a compact, JSON-safe summary suitable for Snapshot.notes."""
    return [
        {
            "name": item.get("name"),
            "status": item.get("status"),
            "duration_seconds": item.get("duration_seconds", 0),
            "error": item.get("error"),
            "optional": bool(item.get("optional", True)),
        }
        for item in stage_results
    ]


def final_snapshot_status(stage_results, *, orchestration_failed=False):
    """Map stage outcomes to the public snapshot status contract.

    ``partial`` preserves the existing behavior when optional integrations
    fail. A required stage or orchestration failure makes the job retryable.
    """
    if orchestration_failed or any(
        item.get("status") == "failed" and not item.get("optional", True)
        for item in stage_results
    ):
        return "failed"
    if any(item.get("status") == "failed" for item in stage_results):
        return "partial"
    return "complete"

