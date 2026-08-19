"""GA4 retrieval and per-snapshot cache helpers.

GA4 data is stored in the existing ``ga4_metrics`` table.  A lightweight
marker row lets us distinguish a cached empty report from a period that has
not yet been requested.
"""

from collections import defaultdict
from datetime import datetime
import os

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
from google.oauth2 import service_account

from app.models import Ga4DailyMetric, Ga4Metric, db
from services.google_accounts import get_credentials_path_for_client


GA4_REPORT_METRICS = (
    "totalUsers",
    "sessions",
    "averageSessionDuration",
    "eventCount",
    "engagementRate",
)

GA4_DIMENSIONS = {
    # This is the channel grouping shown in GA4's Traffic acquisition report.
    "channel": "sessionPrimaryChannelGroup",
    "page_path": "pagePath",
    "country": "country",
    "device": "deviceCategory",
}

_CACHE_MARKER_PREFIX = "__ga4_cache__"
GA4_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("GA4_REQUEST_TIMEOUT_SECONDS", "30"))


def _cache_marker(dimension_key):
    return f"{_CACHE_MARKER_PREFIX}::{dimension_key}"


def _credentials_for_client(client):
    credentials_path = get_credentials_path_for_client(client)
    if not credentials_path or not os.path.isfile(credentials_path):
        raise ValueError(
            "No usable Google Analytics credentials are configured for this project. "
            "Select an active Google account in Project Settings."
        )
    return service_account.Credentials.from_service_account_file(credentials_path)


def fetch_ga4_metrics(client, start_date, end_date, dimension_keys):
    """Fetch GA4 rows for one or more supported dimensions without persisting."""
    if not client.ga4_property_id:
        raise ValueError("This project does not have a GA4 property ID configured.")

    unsupported = set(dimension_keys) - set(GA4_DIMENSIONS)
    if unsupported:
        raise ValueError("Unsupported GA4 view requested.")

    analytics = BetaAnalyticsDataClient(credentials=_credentials_for_client(client))
    result = defaultdict(list)

    for dimension_key in dimension_keys:
        request = RunReportRequest(
            property=f"properties/{client.ga4_property_id}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            metrics=[Metric(name=name) for name in GA4_REPORT_METRICS],
            dimensions=[Dimension(name=GA4_DIMENSIONS[dimension_key])],
        )
        response = analytics.run_report(request, timeout=GA4_REQUEST_TIMEOUT_SECONDS)
        for row in response.rows:
            result[dimension_key].append({
                "dimension": row.dimension_values[0].value,
                "metrics": {
                    metric_name: float(row.metric_values[index].value)
                    for index, metric_name in enumerate(GA4_REPORT_METRICS)
                },
            })
    return result


def fetch_ga4_daily_metrics(client, start_date, end_date):
    """Fetch one non-overlapping GA4 total per calendar day.

    This intentionally uses only the ``date`` dimension. Summing existing
    channel/country/device reports would multiply the same sessions.
    """
    if not client.ga4_property_id:
        raise ValueError("This project does not have a GA4 property ID configured.")

    analytics = BetaAnalyticsDataClient(credentials=_credentials_for_client(client))
    response = analytics.run_report(
        RunReportRequest(
            property=f"properties/{client.ga4_property_id}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
            dimensions=[Dimension(name="date")],
        ),
        timeout=GA4_REQUEST_TIMEOUT_SECONDS,
    )
    return [
        {
            "metric_date": datetime.strptime(row.dimension_values[0].value, "%Y%m%d").date(),
            "sessions": float(row.metric_values[0].value),
            "total_users": float(row.metric_values[1].value),
        }
        for row in response.rows
    ]


def cache_ga4_daily_metrics(client_id, snapshot_id, rows):
    """Upsert the rolling daily GA4 window in one read plus one commit."""
    if not rows:
        return 0
    dates = [row["metric_date"] for row in rows]
    existing = {
        row.metric_date: row
        for row in Ga4DailyMetric.query.filter(
            Ga4DailyMetric.client_id == client_id,
            Ga4DailyMetric.metric_date.in_(dates),
        ).all()
    }
    for row in rows:
        target = existing.get(row["metric_date"])
        if target is None:
            target = Ga4DailyMetric(client_id=client_id, metric_date=row["metric_date"])
            db.session.add(target)
        target.sessions = row["sessions"]
        target.total_users = row["total_users"]
        target.source_snapshot_id = snapshot_id
    db.session.commit()
    return len(rows)


def _cached_rows(snapshot_id, start_date, end_date, dimension_key):
    return Ga4Metric.query.filter(
        Ga4Metric.snapshot_id == snapshot_id,
        Ga4Metric.period_start == start_date,
        Ga4Metric.period_end == end_date,
        Ga4Metric.dimension.like(f"{dimension_key}::%"),
    ).all()


def _is_cached(snapshot_id, start_date, end_date, dimension_key):
    return db.session.query(Ga4Metric.id).filter(
        Ga4Metric.snapshot_id == snapshot_id,
        Ga4Metric.period_start == start_date,
        Ga4Metric.period_end == end_date,
        Ga4Metric.dimension == _cache_marker(dimension_key),
    ).first() is not None


def cache_ga4_metrics(snapshot, start_date, end_date, dimension_key, rows):
    """Replace one exact snapshot/range/dimension cache entry."""
    try:
        Ga4Metric.query.filter(
            Ga4Metric.snapshot_id == snapshot.id,
            Ga4Metric.period_start == start_date,
            Ga4Metric.period_end == end_date,
            (Ga4Metric.dimension.like(f"{dimension_key}::%")) |
            (Ga4Metric.dimension == _cache_marker(dimension_key)),
        ).delete(synchronize_session=False)

        for row in rows:
            prefixed_dimension = f"{dimension_key}::{row['dimension']}"
            for metric_name, metric_value in row["metrics"].items():
                db.session.add(Ga4Metric(
                    snapshot_id=snapshot.id,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    dimension=prefixed_dimension,
                    period_start=start_date,
                    period_end=end_date,
                ))

        db.session.add(Ga4Metric(
            snapshot_id=snapshot.id,
            metric_name="__cache_marker__",
            metric_value=0,
            dimension=_cache_marker(dimension_key),
            period_start=start_date,
            period_end=end_date,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_or_fetch_snapshot_ga4(snapshot, client, start_date, end_date, dimension_key):
    """Return rows from the exact cache or retrieve and store them live."""
    if _is_cached(snapshot.id, start_date, end_date, dimension_key):
        return _cached_rows(snapshot.id, start_date, end_date, dimension_key), "cached"

    fetched = fetch_ga4_metrics(client, start_date, end_date, [dimension_key])
    cache_ga4_metrics(snapshot, start_date, end_date, dimension_key, fetched[dimension_key])
    return _cached_rows(snapshot.id, start_date, end_date, dimension_key), "live"
