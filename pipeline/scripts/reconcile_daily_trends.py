"""Best-effort recovery of missing daily GA4/GSC history for legacy projects.

This command is intended to run during deployment. It only requests provider data
for a configured source when that project has *no* stored daily rows for the
source. Projects with any existing daily history are deliberately skipped: normal
audits keep those series current, while this command fixes the legacy-data gap
without turning every deployment into a full refresh.

Usage:
    python -m scripts.reconcile_daily_trends --only-missing --days 455
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from sqlalchemy import func

from app import create_app
from app.models import Client, Ga4DailyMetric, GscDailyMetric, db
from scripts.backfill_daily_trends import (
    DEFAULT_HISTORY_DAYS,
    MAX_HISTORY_DAYS,
    backfill_project_daily_trends,
)


DAILY_SOURCES = {
    "ga4": {"model": Ga4DailyMetric, "configuration_field": "ga4_property_id"},
    "gsc": {"model": GscDailyMetric, "configuration_field": "gsc_site_url"},
}


def _daily_row_counts(model: type[Ga4DailyMetric] | type[GscDailyMetric]) -> dict[int, int]:
    """Return daily-row counts by client in one grouped query."""
    rows = db.session.query(model.client_id, func.count(model.id)).group_by(model.client_id).all()
    return {client_id: int(count) for client_id, count in rows}


def build_missing_daily_trend_plan(max_projects: int = 0) -> dict[str, Any]:
    """Build a provider-free plan for configured sources with zero daily rows."""
    if max_projects < 0:
        raise ValueError("max_projects must be zero (unlimited) or a positive integer")

    counts = {source: _daily_row_counts(details["model"]) for source, details in DAILY_SOURCES.items()}
    clients = Client.query.order_by(Client.id.asc()).all()
    candidates: list[dict[str, Any]] = []
    for client in clients:
        sources: dict[str, dict[str, Any]] = {}
        for source, details in DAILY_SOURCES.items():
            configured = bool(getattr(client, details["configuration_field"], None))
            daily_rows = counts[source].get(client.id, 0)
            if not configured:
                action, reason = "skip", "not_configured"
            elif daily_rows:
                action, reason = "skip", "existing_daily_history"
            else:
                action, reason = "sync", "missing_daily_history"
            sources[source] = {
                "configured": configured,
                "daily_rows": daily_rows,
                "action": action,
                "reason": reason,
            }
        if any(source["action"] == "sync" for source in sources.values()):
            candidates.append({"client_id": client.id, "client_name": client.name, "sources": sources})

    selected = candidates if max_projects == 0 else candidates[:max_projects]
    return {
        "scanned_projects": len(clients),
        "eligible_projects": len(candidates),
        "deferred_projects": len(candidates) - len(selected),
        "projects": selected,
    }


def reconcile_missing_daily_trends(
    *, days: int = DEFAULT_HISTORY_DAYS, dry_run: bool = False, max_projects: int = 0
) -> dict[str, Any]:
    """Synchronize planned sources independently, never aborting the batch."""
    days = max(30, min(int(days), MAX_HISTORY_DAYS))
    plan = build_missing_daily_trend_plan(max_projects=max_projects)
    status_counts: Counter[str] = Counter()
    project_results: list[dict[str, Any]] = []

    for project in plan["projects"]:
        source_results: dict[str, dict[str, Any]] = {}
        for source, source_plan in project["sources"].items():
            if source_plan["action"] != "sync":
                continue
            if dry_run:
                result = {"status": "planned", "daily_rows_before": source_plan["daily_rows"]}
            else:
                try:
                    backfill_result = backfill_project_daily_trends(
                        project["client_id"],
                        days=days,
                        include_ga4=source == "ga4",
                        include_gsc=source == "gsc",
                    )
                    provider_result = backfill_result[source]
                    result = {
                        "status": provider_result.get("status", "completed"),
                        "daily_rows_before": source_plan["daily_rows"],
                        "daily_rows_written": provider_result.get("daily_rows_written", 0),
                    }
                except Exception as exc:  # Best effort by design: do not fail deployment.
                    db.session.rollback()
                    result = {
                        "status": "failed",
                        "daily_rows_before": source_plan["daily_rows"],
                        "error": str(exc)[:400],
                    }
            status_counts[result["status"]] += 1
            source_results[source] = result
        project_results.append(
            {"client_id": project["client_id"], "client_name": project["client_name"], "sources": source_results}
        )

    return {
        "days": days,
        "dry_run": dry_run,
        "scanned_projects": plan["scanned_projects"],
        "eligible_projects": plan["eligible_projects"],
        "selected_projects": len(plan["projects"]),
        "deferred_projects": plan["deferred_projects"],
        "source_status_counts": dict(status_counts),
        "projects": project_results,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    for project in summary["projects"]:
        for source, result in project["sources"].items():
            details = [f"client=#{project['client_id']}", f"source={source}", f"status={result['status']}"]
            if "daily_rows_written" in result:
                details.append(f"rows={result['daily_rows_written']}")
            if "error" in result:
                details.append(f"error={result['error']}")
            print("[daily-trend-reconcile] " + " ".join(details))
    print("[daily-trend-reconcile] summary " + json.dumps(summary, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--max-projects", type=int, default=0, help="Maximum eligible projects; 0 means all.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-missing", action="store_true", help="Document the zero-history-only policy.")
    args = parser.parse_args(argv)
    app = create_app()
    with app.app_context():
        summary = reconcile_missing_daily_trends(days=args.days, dry_run=args.dry_run, max_projects=args.max_projects)
        _print_summary(summary)
    # Provider failures are logged per source and intentionally do not fail deployment.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
