"""Read-only data tools exposed to the AI agent.

Every handler receives a server-created ToolContext. No handler accepts a
client/project identifier from the model, which prevents cross-project reads.
"""

from datetime import date, timedelta

from sqlalchemy import func

from app.models import BacklinkHistory, Competitor, CompetitorInsight, CrawlIssue, CrawlPage, Ga4DailyMetric, GscDailyMetric, Snapshot, db
from services.health import get_latest_health_score, serialize_health_score
from services.rankings import get_keyword_movement_data
from services.tool_registry import ToolContext, ToolRegistry


def _require_context(context):
    if not isinstance(context, ToolContext) or not context.client_id:
        raise ValueError("A server-authorized project context is required.")
    return context.client_id


def _date_range(days=30, start_date=None, end_date=None):
    try:
        days = max(7, min(int(days), 90))
        end = date.fromisoformat(end_date) if end_date else date.today()
        start = date.fromisoformat(start_date) if start_date else end - timedelta(days=days - 1)
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD.") from exc
    if start > end or (end - start).days > 90:
        raise ValueError("Choose a date range no longer than 90 days.")
    return start, end


def _daily_rows(model, client_id, fields, *, days=30, start_date=None, end_date=None):
    start, end = _date_range(days, start_date, end_date)
    rows = (model.query.filter(model.client_id == client_id, model.metric_date.between(start, end)).order_by(model.metric_date.asc()).all())
    totals = {field: sum((getattr(row, field) or 0) for row in rows) for field in fields}
    return {"data": [{"date": row.metric_date.isoformat(), **{field: getattr(row, field) for field in fields}} for row in rows], "meta": {"source": "stored_daily_metrics", "start_date": start.isoformat(), "end_date": end.isoformat(), "points": len(rows), "totals": totals}, "citations": [{"type": "daily_metric_range", "start_date": start.isoformat(), "end_date": end.isoformat()}]}


def get_ga4_data(*, context, days=30, start_date=None, end_date=None):
    return _daily_rows(Ga4DailyMetric, _require_context(context), ("sessions", "total_users"), days=days, start_date=start_date, end_date=end_date)


def get_gsc_data(*, context, days=30, start_date=None, end_date=None):
    payload = _daily_rows(GscDailyMetric, _require_context(context), ("clicks", "impressions", "ctr", "average_position"), days=days, start_date=start_date, end_date=end_date)
    impressions = payload["meta"]["totals"]["impressions"]
    payload["meta"]["totals"]["weighted_ctr"] = round(payload["meta"]["totals"]["clicks"] / impressions, 5) if impressions else None
    return payload


def get_rankings(*, context, keyword=None, limit=20):
    client_id = _require_context(context)
    result = get_keyword_movement_data(client_id, search=keyword or "", per_page=limit, history_limit=6)
    return {"data": result["items"], "meta": {"source": "stored_rankings", "summary": result["summary"], "returned": len(result["items"])}, "citations": [{"type": "ranking_snapshots", "snapshot_ids": [point["snapshot_id"] for item in result["items"][:1] for point in item.get("history", [])]}]}


def get_backlinks(*, context, limit=20):
    client_id = _require_context(context)
    rows = (BacklinkHistory.query.join(Snapshot).filter(Snapshot.client_id == client_id, BacklinkHistory.competitor_id.is_(None), Snapshot.status.in_(("complete", "partial"))).order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).limit(limit).all())
    data = [{"snapshot_id": row.snapshot_id, "date": row.snapshot.created_at.date().isoformat(), "total_backlinks": row.total_backlinks or 0, "referring_domains": row.referring_domains or 0, "new_backlinks": row.new_backlinks or 0, "lost_backlinks": row.lost_backlinks or 0} for row in rows]
    return {"data": data, "meta": {"source": "snapshot_backlink_history", "returned": len(data)}, "citations": [{"type": "snapshot", "snapshot_id": row["snapshot_id"]} for row in data]}


def get_crawl_issues(*, context, issue_type=None, limit=20):
    client_id = _require_context(context)
    snapshot = (Snapshot.query.join(CrawlPage, CrawlPage.snapshot_id == Snapshot.id)
                .filter(Snapshot.client_id == client_id, Snapshot.status.in_(("complete", "partial")))
                .order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).first())
    if not snapshot:
        return {"data": [], "meta": {"source": "snapshot_crawl_issues", "reason": "No completed crawl issues stored."}, "citations": []}
    query = CrawlIssue.query.filter_by(snapshot_id=snapshot.id)
    if issue_type:
        query = query.filter(CrawlIssue.issue_type == issue_type)
    groups = (query.with_entities(CrawlIssue.issue_type, CrawlIssue.category, CrawlIssue.issue, func.count(CrawlIssue.id).label("count")).group_by(CrawlIssue.issue_type, CrawlIssue.category, CrawlIssue.issue).order_by(func.count(CrawlIssue.id).desc()).limit(limit).all())
    data = [{"issue_type": row.issue_type, "category": row.category, "issue": row.issue, "count": int(row.count)} for row in groups]
    return {"data": data, "meta": {"source": "snapshot_crawl_issues", "snapshot_id": snapshot.id, "returned": len(data)}, "citations": [{"type": "snapshot", "snapshot_id": snapshot.id}]}


def get_competitor_data(*, context, competitor_id=None, limit=20):
    client_id = _require_context(context)
    query = CompetitorInsight.query.join(Competitor).filter(CompetitorInsight.client_id == client_id)
    if competitor_id:
        query = query.filter(CompetitorInsight.competitor_id == competitor_id)
    rows = query.order_by(CompetitorInsight.created_at.desc(), CompetitorInsight.id.desc()).limit(limit).all()
    data = [{"competitor_id": row.competitor_id, "domain": row.competitor.domain, "snapshot_id": row.snapshot_id, "status": row.status, "summary": row.summary or {}, "error": row.error_message} for row in rows]
    return {"data": data, "meta": {"source": "stored_competitor_insights", "returned": len(data)}, "citations": [{"type": "snapshot", "snapshot_id": row["snapshot_id"]} for row in data if row["snapshot_id"]]}


def get_project_health(*, context):
    record = get_latest_health_score(_require_context(context))
    return {"data": serialize_health_score(record), "meta": {"source": "persisted_health_score"}, "citations": [{"type": "snapshot", "snapshot_id": record.snapshot_id}] if record else []}


def build_project_tool_registry():
    return ToolRegistry().register_standard_tools({
        "get_ga4_data": get_ga4_data, "get_gsc_data": get_gsc_data,
        "get_rankings": get_rankings, "get_backlinks": get_backlinks,
        "get_crawl_issues": get_crawl_issues, "get_competitor_data": get_competitor_data,
        "get_project_health": get_project_health,
    })
