"""Fast, read-only 30/60/90-day trend queries for the project dashboard."""

from collections import defaultdict
from datetime import date, timedelta

from app.models import (
    BacklinkHistory,
    CrawlIssue,
    CrawlPage,
    Ga4DailyMetric,
    GscDailyMetric,
    Snapshot,
    db,
)


VALID_TREND_WINDOWS = (30, 60, 90)
COMPLETE_SNAPSHOT_STATUSES = ("complete", "partial")


def _date_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _summary(points, *, inverse_health=False):
    values = [point["value"] for point in points if point.get("value") is not None]
    if not values:
        return {
            "latest": None, "previous": None, "absolute_change": None,
            "percent_change": None, "direction": "neutral", "health_direction": "neutral",
            "data_points": 0,
        }
    latest = values[-1]
    previous = values[0] if len(values) > 1 else None
    absolute_change = latest - previous if previous is not None else None
    percent_change = round((absolute_change / previous) * 100, 1) if previous not in (None, 0) else None
    if absolute_change is None or absolute_change == 0:
        direction = "neutral"
    else:
        direction = "up" if absolute_change > 0 else "down"
    health_direction = direction
    if inverse_health and direction in {"up", "down"}:
        health_direction = "down" if direction == "up" else "up"
    return {
        "latest": latest,
        "previous": previous,
        "absolute_change": absolute_change,
        "percent_change": percent_change,
        "direction": direction,
        "health_direction": health_direction,
        "data_points": len(values),
    }


def _daily_points(rows, attribute):
    return [{"date": _date_value(row.metric_date), "value": getattr(row, attribute)} for row in rows]


def _latest_snapshot_point_per_day(snapshots, values_by_snapshot):
    """Avoid a misleading double point if users run two audits on one day."""
    points_by_date = {}
    # Snapshots are ordered oldest-to-newest, so later same-day audits replace
    # earlier observations and the chart shows the latest state for that day.
    for snapshot in snapshots:
        value = values_by_snapshot.get(snapshot.id)
        if value is None:
            continue
        points_by_date[_date_value(snapshot.created_at.date())] = {
            "date": _date_value(snapshot.created_at.date()),
            "value": value,
            "snapshot_id": snapshot.id,
        }
    return [points_by_date[key] for key in sorted(points_by_date)]


def get_project_trends(client_id, days=30, *, end_date=None):
    """Return chart-ready project trends using stored data only.

    Daily Google aggregates provide traffic/search accuracy. Crawl and backlink
    metrics remain audit observations because they only exist after a crawl.
    """
    if days not in VALID_TREND_WINDOWS:
        raise ValueError("Trend window must be 30, 60, or 90 days.")
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=days - 1)

    ga4_rows = Ga4DailyMetric.query.filter(
        Ga4DailyMetric.client_id == client_id,
        Ga4DailyMetric.metric_date.between(start_date, end_date),
    ).order_by(Ga4DailyMetric.metric_date.asc()).all()
    gsc_rows = GscDailyMetric.query.filter(
        GscDailyMetric.client_id == client_id,
        GscDailyMetric.metric_date.between(start_date, end_date),
    ).order_by(GscDailyMetric.metric_date.asc()).all()
    snapshots = Snapshot.query.filter(
        Snapshot.client_id == client_id,
        Snapshot.status.in_(COMPLETE_SNAPSHOT_STATUSES),
        Snapshot.created_at >= start_date,
    ).order_by(Snapshot.created_at.asc(), Snapshot.id.asc()).all()
    snapshot_ids = [snapshot.id for snapshot in snapshots]

    crawl_values = {}
    backlink_values = {}
    referring_domain_values = {}
    if snapshot_ids:
        crawled_snapshot_ids = {
            snapshot_id
            for snapshot_id, page_count in db.session.query(
                CrawlPage.snapshot_id, db.func.count(CrawlPage.id),
            ).filter(CrawlPage.snapshot_id.in_(snapshot_ids)).group_by(CrawlPage.snapshot_id).all()
            if page_count > 0
        }
        issue_counts = dict(
            db.session.query(CrawlIssue.snapshot_id, db.func.count(CrawlIssue.id))
            .filter(CrawlIssue.snapshot_id.in_(crawled_snapshot_ids or [-1]))
            .group_by(CrawlIssue.snapshot_id)
            .all()
        )
        crawl_values = {snapshot_id: issue_counts.get(snapshot_id, 0) for snapshot_id in crawled_snapshot_ids}
        for row in BacklinkHistory.query.filter(
            BacklinkHistory.snapshot_id.in_(snapshot_ids),
            BacklinkHistory.competitor_id.is_(None),
        ).all():
            backlink_values[row.snapshot_id] = row.total_backlinks or 0
            referring_domain_values[row.snapshot_id] = row.referring_domains or 0

    series = {
        "ga4_sessions": _daily_points(ga4_rows, "sessions"),
        "gsc_clicks": _daily_points(gsc_rows, "clicks"),
        "gsc_ctr": [
            {"date": _date_value(row.metric_date), "value": round((row.ctr or 0) * 100, 3)}
            for row in gsc_rows
        ],
        "crawl_issues": _latest_snapshot_point_per_day(snapshots, crawl_values),
        "backlinks": _latest_snapshot_point_per_day(snapshots, backlink_values),
        "referring_domains": _latest_snapshot_point_per_day(snapshots, referring_domain_values),
    }
    return {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "series": series,
        "summary": {
            "ga4_sessions": _summary(series["ga4_sessions"]),
            "gsc_clicks": _summary(series["gsc_clicks"]),
            "gsc_ctr": _summary(series["gsc_ctr"]),
            "crawl_issues": _summary(series["crawl_issues"], inverse_health=True),
            "backlinks": _summary(series["backlinks"]),
            "referring_domains": _summary(series["referring_domains"]),
        },
        "meta": {
            "google_data_is_daily": True,
            "audit_data_is_snapshot_based": True,
            "available_snapshot_count": len(snapshots),
            "daily_ga4_points": len(ga4_rows),
            "daily_gsc_points": len(gsc_rows),
        },
    }
