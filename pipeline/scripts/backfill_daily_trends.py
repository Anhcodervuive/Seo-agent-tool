"""Backfill stored GA4/GSC daily history for one project, without an audit.

Run intentionally for a single project after confirming its Google settings:
    python -m scripts.backfill_daily_trends --client-id 2 --days 455

The default is enough to make 30/60/90-day year-over-year comparisons
possible when the providers still expose the requested history. The script
never crawls a site, writes a report, or invokes the AI provider.
"""

import argparse
from datetime import date, timedelta

from app import create_app
from app.models import Client, Snapshot, db
from services.ga4 import cache_ga4_daily_metrics, fetch_ga4_daily_metrics
from services.gsc import cache_gsc_daily_metrics, fetch_gsc_daily_metrics


DEFAULT_HISTORY_DAYS = 455
MAX_HISTORY_DAYS = 455
GSC_DELAY_DAYS = 3


def daily_trend_ranges(days, *, today=None):
    """Return provider-safe inclusive ranges for a historical daily sync."""
    today = today or date.today()
    days = max(30, min(int(days), MAX_HISTORY_DAYS))
    ga4_end = today
    gsc_end = today - timedelta(days=GSC_DELAY_DAYS)
    return {
        "ga4": (ga4_end - timedelta(days=days - 1), ga4_end),
        "gsc": (gsc_end - timedelta(days=days - 1), gsc_end),
    }


def _latest_snapshot_id(client_id):
    snapshot = (
        Snapshot.query.filter(
            Snapshot.client_id == client_id,
            Snapshot.status.in_(("complete", "partial")),
        ).order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).first()
    )
    return snapshot.id if snapshot else None


def backfill_project_daily_trends(client_id, *, days=DEFAULT_HISTORY_DAYS, include_ga4=True, include_gsc=True, dry_run=False):
    """Backfill a single project's stored daily rows and return a result map."""
    client = db.session.get(Client, client_id)
    if not client:
        raise ValueError(f"Project #{client_id} does not exist.")
    ranges = daily_trend_ranges(days)
    source_snapshot_id = _latest_snapshot_id(client.id)
    result = {
        "client_id": client.id,
        "days": max(30, min(int(days), MAX_HISTORY_DAYS)),
        "source_snapshot_id": source_snapshot_id,
        "ga4": {"status": "skipped", "rows": 0, "range": ranges["ga4"]},
        "gsc": {"status": "skipped", "rows": 0, "range": ranges["gsc"]},
    }
    if dry_run:
        return result

    if include_ga4:
        if not client.ga4_property_id:
            result["ga4"]["status"] = "not_configured"
        else:
            start, end = ranges["ga4"]
            rows = fetch_ga4_daily_metrics(client, start.isoformat(), end.isoformat())
            result["ga4"]["rows"] = cache_ga4_daily_metrics(client.id, source_snapshot_id, rows)
            result["ga4"]["status"] = "completed"

    if include_gsc:
        if not client.gsc_site_url:
            result["gsc"]["status"] = "not_configured"
        else:
            start, end = ranges["gsc"]
            rows = fetch_gsc_daily_metrics(client, start.isoformat(), end.isoformat())
            result["gsc"]["rows"] = cache_gsc_daily_metrics(client.id, source_snapshot_id, rows)
            result["gsc"]["status"] = "completed"
    return result


def _format_range(value):
    start, end = value
    return f"{start.isoformat()}..{end.isoformat()}"


def main():
    parser = argparse.ArgumentParser(description="Backfill stored daily GA4/GSC trend history for one project.")
    parser.add_argument("--client-id", type=int, required=True, help="Project/client ID to backfill.")
    parser.add_argument("--days", type=int, default=DEFAULT_HISTORY_DAYS, help=f"History to request (30–{MAX_HISTORY_DAYS}; default: {DEFAULT_HISTORY_DAYS}).")
    parser.add_argument("--ga4-only", action="store_true", help="Backfill GA4 only.")
    parser.add_argument("--gsc-only", action="store_true", help="Backfill GSC only.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned provider ranges without making provider calls.")
    args = parser.parse_args()
    if args.ga4_only and args.gsc_only:
        parser.error("Choose at most one of --ga4-only and --gsc-only.")

    app = create_app()
    with app.app_context():
        result = backfill_project_daily_trends(
            args.client_id,
            days=args.days,
            include_ga4=not args.gsc_only,
            include_gsc=not args.ga4_only,
            dry_run=args.dry_run,
        )
        mode = "Planned" if args.dry_run else "Completed"
        for provider in ("ga4", "gsc"):
            item = result[provider]
            print(
                f"{mode} {provider.upper()}: status={item['status']} rows={item['rows']} range={_format_range(item['range'])}",
                flush=True,
            )


if __name__ == "__main__":
    main()
