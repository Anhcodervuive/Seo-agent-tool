"""Fast, read-only project trend queries and comparable-period calculations.

Daily Google rows are flow metrics, so their cards compare totals over equal
calendar windows. Crawl and backlink rows are point-in-time audit observations,
so their cards compare the latest observation in each comparable window.
"""

from datetime import date, datetime, time, timedelta

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
MIN_DAILY_COMPARISON_COVERAGE = 0.70
# Search Console normally lags a few days. Keep a small extra query buffer so
# its latest stored date can anchor an equal-window comparison without a second
# query, while still reading a bounded index-backed range.
DAILY_COMPARISON_DELAY_BUFFER_DAYS = 14


def _date_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _parse_date(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def _shift_year(value, years=-1):
    """Move a date by calendar year, using 28 February for leap-day anchors."""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _direction(change):
    if change is None or change == 0:
        return "neutral"
    return "up" if change > 0 else "down"


def _health_direction(direction, inverse_health=False):
    if inverse_health and direction in {"up", "down"}:
        return "down" if direction == "up" else "up"
    return direction


def _percent_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return round(((current - previous) / previous) * 100, 1)


def _summary(points, *, inverse_health=False):
    """Compatibility summary for callers that compare first and last points.

    The Trends dashboard now uses comparable windows below. Keeping this helper
    stable preserves the lightweight unit contract used by older callers.
    """
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
    direction = _direction(absolute_change)
    return {
        "latest": latest,
        "previous": previous,
        "absolute_change": absolute_change,
        "percent_change": _percent_change(latest, previous),
        "direction": direction,
        "health_direction": _health_direction(direction, inverse_health),
        "data_points": len(values),
    }


def _daily_points(rows, attribute):
    return [
        {"date": _date_value(row.metric_date), "value": getattr(row, attribute)}
        for row in rows
    ]


def _gsc_ctr_points(rows):
    return [
        {
            "date": _date_value(row.metric_date),
            "value": round(((row.clicks or 0) / row.impressions) * 100, 3)
            if row.impressions else 0,
        }
        for row in rows
    ]


def _latest_snapshot_point_per_day(snapshots, values_by_snapshot):
    """Avoid a misleading double point if users run two audits on one day."""
    points_by_date = {}
    # Snapshots are ordered oldest-to-newest, so later same-day audits replace
    # earlier observations and the chart shows the latest state for that day.
    for snapshot in snapshots:
        value = values_by_snapshot.get(snapshot.id)
        if value is None:
            continue
        snapshot_date = snapshot.created_at.date()
        points_by_date[_date_value(snapshot_date)] = {
            "date": _date_value(snapshot_date),
            "value": value,
            "snapshot_id": snapshot.id,
        }
    return [points_by_date[key] for key in sorted(points_by_date)]


def _window(start, end):
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": (end - start).days + 1,
    }


def _daily_window(rows, start, end, value_getter):
    selected = [row for row in rows if start <= row.metric_date <= end]
    expected_days = (end - start).days + 1
    points = len(selected)
    return {
        "value": value_getter(selected) if selected else None,
        "points": points,
        "expected_days": expected_days,
        "coverage": round(min(1, points / expected_days), 3),
        "window": _window(start, end),
        "anchor_date": end.isoformat(),
    }


def _sum_attribute(attribute):
    return lambda rows: sum((getattr(row, attribute) or 0) for row in rows)


def _weighted_ctr(rows):
    impressions = sum((row.impressions or 0) for row in rows)
    if not impressions:
        return 0
    clicks = sum((row.clicks or 0) for row in rows)
    return round((clicks / impressions) * 100, 4)


def _comparison(current, baseline, *, label, reason_prefix, inverse_health=False):
    current_value = current.get("value")
    baseline_value = baseline.get("value")
    if current_value is None:
        return {
            "label": label,
            "available": False,
            "reason": f"No stored data in the current {reason_prefix}.",
            "current": current,
            "baseline": baseline,
            "absolute_change": None,
            "percent_change": None,
            "direction": "neutral",
            "health_direction": "neutral",
        }
    if baseline_value is None:
        return {
            "label": label,
            "available": False,
            "reason": f"No comparable data in the {reason_prefix}.",
            "current": current,
            "baseline": baseline,
            "absolute_change": None,
            "percent_change": None,
            "direction": "neutral",
            "health_direction": "neutral",
        }
    # Audit observations are deliberately irregular. Their point count is
    # meaningful, but a daily coverage percentage is not; it is None there.
    daily_coverage = current.get("coverage") is not None or baseline.get("coverage") is not None
    if daily_coverage and (
        current.get("coverage", 0) < MIN_DAILY_COMPARISON_COVERAGE
        or baseline.get("coverage", 0) < MIN_DAILY_COMPARISON_COVERAGE
    ):
        return {
            "label": label,
            "available": False,
            "reason": "Need at least 70% daily coverage in both comparable windows.",
            "current": current,
            "baseline": baseline,
            "absolute_change": None,
            "percent_change": None,
            "direction": "neutral",
            "health_direction": "neutral",
        }
    absolute_change = current_value - baseline_value
    direction = _direction(absolute_change)
    return {
        "label": label,
        "available": True,
        "reason": None,
        "current": current,
        "baseline": baseline,
        "absolute_change": absolute_change,
        "percent_change": _percent_change(current_value, baseline_value),
        "direction": direction,
        "health_direction": _health_direction(direction, inverse_health),
    }


def _daily_metric_summary(rows, *, requested_end, days, value_getter, inverse_health=False):
    rows = [row for row in rows if row.metric_date <= requested_end]
    if not rows:
        empty_window = _daily_window([], requested_end - timedelta(days=days - 1), requested_end, value_getter)
        period = _comparison(empty_window, empty_window, label="Period change", reason_prefix="selected window", inverse_health=inverse_health)
        year = _comparison(empty_window, empty_window, label="Year over year", reason_prefix="same period last year", inverse_health=inverse_health)
        return {
            "latest": None, "previous": None, "absolute_change": None, "percent_change": None,
            "direction": "neutral", "health_direction": "neutral", "data_points": 0,
            "comparison": {"period_over_period": period, "year_over_year": year},
        }

    anchor = max(row.metric_date for row in rows)
    current_start = anchor - timedelta(days=days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    year_start = _shift_year(current_start)
    year_end = _shift_year(anchor)
    current = _daily_window(rows, current_start, anchor, value_getter)
    previous = _daily_window(rows, previous_start, previous_end, value_getter)
    last_year = _daily_window(rows, year_start, year_end, value_getter)
    period = _comparison(
        current, previous,
        label="MoM" if days == 30 else "Period change",
        reason_prefix=f"previous {days}-day window",
        inverse_health=inverse_health,
    )
    year = _comparison(
        current, last_year,
        label="YoY",
        reason_prefix="same period last year",
        inverse_health=inverse_health,
    )
    return {
        "latest": current["value"],
        "previous": previous["value"],
        "absolute_change": period["absolute_change"],
        "percent_change": period["percent_change"],
        "direction": period["direction"],
        "health_direction": period["health_direction"],
        "data_points": current["points"],
        "anchor_date": anchor.isoformat(),
        "comparison": {"period_over_period": period, "year_over_year": year},
    }


def _points_in_window(points, start, end):
    return [point for point in points if start <= _parse_date(point["date"]) <= end]


def _latest_observation(points, start, end):
    selected = _points_in_window(points, start, end)
    if not selected:
        return {
            "value": None,
            "points": 0,
            "coverage": None,
            "window": _window(start, end),
            "anchor_date": None,
            "snapshot_id": None,
        }
    latest = selected[-1]
    return {
        "value": latest["value"],
        "points": len(selected),
        "coverage": None,
        "window": _window(start, end),
        "anchor_date": latest["date"],
        "snapshot_id": latest.get("snapshot_id"),
    }


def _snapshot_metric_summary(points, *, end_date, days, inverse_health=False):
    current_start = end_date - timedelta(days=days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    year_start = _shift_year(current_start)
    year_end = _shift_year(end_date)
    current = _latest_observation(points, current_start, end_date)
    previous = _latest_observation(points, previous_start, previous_end)
    last_year = _latest_observation(points, year_start, year_end)
    period = _comparison(
        current, previous,
        label="MoM" if days == 30 else "Period change",
        reason_prefix=f"previous {days}-day window",
        inverse_health=inverse_health,
    )
    year = _comparison(
        current, last_year,
        label="YoY",
        reason_prefix="same period last year",
        inverse_health=inverse_health,
    )
    return {
        "latest": current["value"],
        "previous": previous["value"],
        "absolute_change": period["absolute_change"],
        "percent_change": period["percent_change"],
        "direction": period["direction"],
        "health_direction": period["health_direction"],
        "data_points": current["points"],
        "anchor_date": current["anchor_date"],
        "comparison": {"period_over_period": period, "year_over_year": year},
    }


def _comparison_query_start(end_date, days):
    current_start = end_date - timedelta(days=days - 1)
    previous_start = current_start - timedelta(days=days)
    year_start = _shift_year(current_start)
    return min(previous_start, year_start) - timedelta(days=DAILY_COMPARISON_DELAY_BUFFER_DAYS)


def _series_for_window(points, start_date, end_date):
    return _points_in_window(points, start_date, end_date)


def _current_series_window(summary, fallback_start, fallback_end):
    comparison = (summary.get("comparison") or {}).get("period_over_period") or {}
    window_value = (comparison.get("current") or {}).get("window") or {}
    try:
        return _parse_date(window_value["start_date"]), _parse_date(window_value["end_date"])
    except (KeyError, TypeError, ValueError):
        return fallback_start, fallback_end


def get_project_trends(client_id, days=30, *, end_date=None):
    """Return chart-ready project trends from stored data only.

    The endpoint never calls GA4, GSC, DataForSEO, or LibreCrawl. It reads a
    bounded lookback range: enough for the selected period, the preceding equal
    period, and the same calendar period last year.
    """
    if days not in VALID_TREND_WINDOWS:
        raise ValueError("Trend window must be 30, 60, or 90 days.")
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=days - 1)
    comparison_start = _comparison_query_start(end_date, days)

    ga4_rows = Ga4DailyMetric.query.filter(
        Ga4DailyMetric.client_id == client_id,
        Ga4DailyMetric.metric_date.between(comparison_start, end_date),
    ).order_by(Ga4DailyMetric.metric_date.asc()).all()
    gsc_rows = GscDailyMetric.query.filter(
        GscDailyMetric.client_id == client_id,
        GscDailyMetric.metric_date.between(comparison_start, end_date),
    ).order_by(GscDailyMetric.metric_date.asc()).all()

    snapshot_start = datetime.combine(comparison_start, time.min)
    snapshot_end = datetime.combine(end_date + timedelta(days=1), time.min)
    snapshots = Snapshot.query.filter(
        Snapshot.client_id == client_id,
        Snapshot.status.in_(COMPLETE_SNAPSHOT_STATUSES),
        Snapshot.created_at >= snapshot_start,
        Snapshot.created_at < snapshot_end,
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

    all_series = {
        "ga4_sessions": _daily_points(ga4_rows, "sessions"),
        "gsc_clicks": _daily_points(gsc_rows, "clicks"),
        "gsc_ctr": _gsc_ctr_points(gsc_rows),
        "crawl_issues": _latest_snapshot_point_per_day(snapshots, crawl_values),
        "backlinks": _latest_snapshot_point_per_day(snapshots, backlink_values),
        "referring_domains": _latest_snapshot_point_per_day(snapshots, referring_domain_values),
    }
    summary = {
        "ga4_sessions": _daily_metric_summary(
            ga4_rows, requested_end=end_date, days=days, value_getter=_sum_attribute("sessions"),
        ),
        "gsc_clicks": _daily_metric_summary(
            gsc_rows, requested_end=end_date, days=days, value_getter=_sum_attribute("clicks"),
        ),
        "gsc_ctr": _daily_metric_summary(
            gsc_rows, requested_end=end_date, days=days, value_getter=_weighted_ctr,
        ),
        "crawl_issues": _snapshot_metric_summary(
            all_series["crawl_issues"], end_date=end_date, days=days, inverse_health=True,
        ),
        "backlinks": _snapshot_metric_summary(
            all_series["backlinks"], end_date=end_date, days=days,
        ),
        "referring_domains": _snapshot_metric_summary(
            all_series["referring_domains"], end_date=end_date, days=days,
        ),
    }
    # GSC can lag several days. Its aggregate comparison and chart should use
    # the same latest complete window, not a 27-day drawing paired with a
    # 30-day card. Snapshot metrics keep the user-selected calendar window.
    series = {}
    for metric, points in all_series.items():
        metric_start, metric_end = _current_series_window(summary[metric], start_date, end_date)
        series[metric] = _series_for_window(points, metric_start, metric_end)
    return {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "series": series,
        "summary": summary,
        "meta": {
            "google_data_is_daily": True,
            "audit_data_is_snapshot_based": True,
            "available_snapshot_count": len(_series_for_window(all_series["crawl_issues"], start_date, end_date)),
            "daily_ga4_points": len(series["ga4_sessions"]),
            "daily_gsc_points": len(series["gsc_clicks"]),
            "comparison_query_start": comparison_start.isoformat(),
            "daily_minimum_coverage": MIN_DAILY_COMPARISON_COVERAGE,
        },
    }
