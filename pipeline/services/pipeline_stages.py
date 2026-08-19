"""Stage planning and execution helpers for snapshot audits.

The stage implementations remain in :mod:`pipeline_runner` for backwards
compatibility with existing imports.  This module owns the orchestration
contract so new stages can be added without editing the worker lifecycle.
"""

from dataclasses import dataclass
from time import monotonic
from typing import Callable, Any


@dataclass(frozen=True)
class StageSpec:
    """A named pipeline stage and whether its failure is optional."""

    name: str
    run: Callable[[], Any]
    optional: bool = True


def build_stage_plan(run_type: str, *, crawl, ga4, gsc, rankings, backlinks, competitor_insights):
    """Build the ordered stage plan for a snapshot run.

    ``rank_check`` intentionally skips crawl, analytics, backlinks, competitor
    data and report generation.  Callables are injected so this module is
    independent of Flask/SQLAlchemy and can be tested in isolation.
    """
    if run_type == "rank_check":
        return [StageSpec("rankings", rankings, optional=False)]
    return [
        StageSpec("crawl", crawl, optional=False),
        StageSpec("ga4", ga4),
        StageSpec("gsc", gsc),
        StageSpec("rankings", rankings),
        StageSpec("backlinks", backlinks),
        StageSpec("competitor_insights", competitor_insights),
    ]


def execute_stage(spec: StageSpec):
    """Execute one stage and return structured timing/status information."""
    started = monotonic()
    try:
        value = spec.run()
        status = "partial" if isinstance(value, dict) and value.get("errors") else "complete"
        return {
            "name": spec.name,
            "status": status,
            "duration_seconds": round(monotonic() - started, 3),
            "value": value,
            "error": None,
            "optional": spec.optional,
        }
    except Exception as exc:  # The caller decides whether to continue/retry.
        return {
            "name": spec.name,
            "status": "failed",
            "duration_seconds": round(monotonic() - started, 3),
            "value": None,
            "error": str(exc),
            "optional": spec.optional,
        }


def has_fatal_stage_failure(stage_results):
    """Return true when a required stage failed."""
    return any(
        item.get("status") == "failed" and not item.get("optional", True)
        for item in stage_results
    )
