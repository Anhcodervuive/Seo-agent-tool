"""Search Console retrieval and per-snapshot cache helpers."""

import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.models import GscDailyMetric, GscMetric, db
from services.google_accounts import get_credentials_path_for_client


GSC_VIEWS = {
    "queries": "query",
    "urls": "page",
    "country": "country",
    "device": "device",
}

_CACHE_MARKER_PREFIX = "__gsc_cache__"


def _cache_marker(view_name):
    return f"{_CACHE_MARKER_PREFIX}::{view_name}"


def _credentials_for_client(client):
    credentials_path = get_credentials_path_for_client(client)
    if not credentials_path or not os.path.isfile(credentials_path):
        raise ValueError(
            "No usable Search Console credentials are configured for this project. "
            "Select an active Google account in Project Settings."
        )
    return service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )


def fetch_gsc_metrics(client, start_date, end_date, view_names):
    """Fetch selected Search Console report views without persisting them."""
    if not client.gsc_site_url:
        raise ValueError("This project does not have a Search Console property configured.")

    unsupported = set(view_names) - set(GSC_VIEWS)
    if unsupported:
        raise ValueError("Unsupported Search Console view requested.")

    service = build("searchconsole", "v1", credentials=_credentials_for_client(client))
    results = {}
    for view_name in view_names:
        response = service.searchanalytics().query(
            siteUrl=client.gsc_site_url,
            body={
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": [GSC_VIEWS[view_name]],
                "rowLimit": 1000,
            },
        ).execute(num_retries=1)
        results[view_name] = [
            {
                "label": row["keys"][0] if row.get("keys") else "",
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position"),
            }
            for row in response.get("rows", [])
        ]
    return results


def fetch_gsc_daily_metrics(client, start_date, end_date):
    """Fetch daily Search Console totals without query/page duplication."""
    if not client.gsc_site_url:
        raise ValueError("This project does not have a Search Console property configured.")

    service = build("searchconsole", "v1", credentials=_credentials_for_client(client))
    response = service.searchanalytics().query(
        siteUrl=client.gsc_site_url,
        body={
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["date"],
            "rowLimit": 1000,
        },
    ).execute(num_retries=1)
    rows = []
    for row in response.get("rows", []):
        impressions = int(row.get("impressions", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        rows.append({
            "metric_date": datetime.strptime(row["keys"][0], "%Y-%m-%d").date(),
            "clicks": clicks,
            "impressions": impressions,
            "ctr": clicks / impressions if impressions else 0,
            "average_position": float(row["position"]) if row.get("position") is not None else None,
        })
    return rows


def cache_gsc_daily_metrics(client_id, snapshot_id, rows):
    """Upsert the rolling daily GSC window in one read plus one commit."""
    if not rows:
        return 0
    dates = [row["metric_date"] for row in rows]
    existing = {
        row.metric_date: row
        for row in GscDailyMetric.query.filter(
            GscDailyMetric.client_id == client_id,
            GscDailyMetric.metric_date.in_(dates),
        ).all()
    }
    for row in rows:
        target = existing.get(row["metric_date"])
        if target is None:
            target = GscDailyMetric(client_id=client_id, metric_date=row["metric_date"])
            db.session.add(target)
        target.clicks = row["clicks"]
        target.impressions = row["impressions"]
        target.ctr = row["ctr"]
        target.average_position = row["average_position"]
        target.source_snapshot_id = snapshot_id
    db.session.commit()
    return len(rows)


def _view_prefix(view_name):
    return "page" if view_name == "urls" else ("query" if view_name == "queries" else view_name)


def _view_filter(view_name):
    prefix = _view_prefix(view_name)
    if view_name == "urls":
        return GscMetric.page.like(f"{prefix}::%")
    return GscMetric.query.like(f"{prefix}::%")


def _cached_rows(snapshot_id, start_date, end_date, view_name):
    return db.session.query(GscMetric).filter(
        GscMetric.snapshot_id == snapshot_id,
        GscMetric.period_start == start_date,
        GscMetric.period_end == end_date,
        _view_filter(view_name),
    ).all()


def _is_cached(snapshot_id, start_date, end_date, view_name):
    return db.session.query(GscMetric.id).filter(
        GscMetric.snapshot_id == snapshot_id,
        GscMetric.period_start == start_date,
        GscMetric.period_end == end_date,
        GscMetric.query == _cache_marker(view_name),
    ).first() is not None


def cache_gsc_metrics(snapshot, start_date, end_date, view_name, rows):
    """Replace one exact snapshot/range/view cache entry."""
    try:
        db.session.query(GscMetric).filter(
            GscMetric.snapshot_id == snapshot.id,
            GscMetric.period_start == start_date,
            GscMetric.period_end == end_date,
            _view_filter(view_name) | (GscMetric.query == _cache_marker(view_name)),
        ).delete(synchronize_session=False)

        prefix = _view_prefix(view_name)
        for row in rows:
            kwargs = {
                "snapshot_id": snapshot.id,
                "clicks": row["clicks"],
                "impressions": row["impressions"],
                "ctr": row["ctr"],
                "position": row["position"],
                "period_start": start_date,
                "period_end": end_date,
            }
            if view_name == "urls":
                kwargs["page"] = f"{prefix}::{row['label']}"
            else:
                kwargs["query"] = f"{prefix}::{row['label']}"
            db.session.add(GscMetric(**kwargs))

        db.session.add(GscMetric(
            snapshot_id=snapshot.id,
            query=_cache_marker(view_name),
            clicks=0,
            impressions=0,
            ctr=0,
            period_start=start_date,
            period_end=end_date,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_or_fetch_snapshot_gsc(snapshot, client, start_date, end_date, view_name):
    """Return an exact cached view, or retrieve it once from Search Console."""
    if _is_cached(snapshot.id, start_date, end_date, view_name):
        return _cached_rows(snapshot.id, start_date, end_date, view_name), "cached"

    fetched = fetch_gsc_metrics(client, start_date, end_date, [view_name])
    cache_gsc_metrics(snapshot, start_date, end_date, view_name, fetched[view_name])
    return _cached_rows(snapshot.id, start_date, end_date, view_name), "live"
