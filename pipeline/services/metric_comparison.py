"""Small, reusable comparisons for non-overlapping daily metric windows."""

from datetime import date, timedelta

from sqlalchemy import func

from app.models import db


def _as_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def compare_daily_windows(model, client_id, fields, *, end_date=None, days=30):
    """Compare two equal calendar windows using stored daily values only.

    The latest available date at or before ``end_date`` is used. This is
    important for GSC, whose data normally arrives a few days late.
    """
    days = max(7, min(int(days), 90))
    anchor = _as_date(end_date) if end_date else date.today()
    latest_date = (
        db.session.query(func.max(model.metric_date))
        .filter(model.client_id == client_id, model.metric_date <= anchor)
        .scalar()
    )
    if not latest_date:
        return {"available": False, "reason": "No stored daily data."}

    current_start = latest_date - timedelta(days=days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)

    def aggregate(start, end):
        selected = [func.coalesce(func.sum(getattr(model, field)), 0).label(field) for field in fields]
        row = (
            db.session.query(func.count(model.id).label("points"), *selected)
            .filter(model.client_id == client_id, model.metric_date.between(start, end))
            .one()
        )
        return {"points": int(row.points or 0), **{field: float(getattr(row, field) or 0) for field in fields}}

    current = aggregate(current_start, latest_date)
    previous = aggregate(previous_start, previous_end)
    coverage = min(current["points"], previous["points"]) / days
    return {
        "available": bool(current["points"] and previous["points"]),
        "coverage": round(min(1, coverage), 3),
        "current": current,
        "previous": previous,
        "current_start": current_start.isoformat(),
        "current_end": latest_date.isoformat(),
        "previous_start": previous_start.isoformat(),
        "previous_end": previous_end.isoformat(),
        "days": days,
    }


def percent_change(current, previous):
    if previous in (None, 0):
        return None
    return (current - previous) / previous
