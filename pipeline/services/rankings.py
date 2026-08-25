"""Read-only ranking services shared by the dashboard, exports, and AI tools."""

from collections import defaultdict

from app.models import Keyword, Ranking, Snapshot, db


VALID_SNAPSHOT_STATUSES = ("complete", "partial")
VALID_FILTERS = {"all", "winners", "losers", "page_1", "page_2", "not_ranking", "check_failed"}


def ranking_lookup_key(keyword, location, device, language="en", competitor_id=None):
    return (
        competitor_id,
        (keyword or "").strip().lower(),
        (location or "").strip().lower(),
        (device or "desktop").strip().lower(),
        (language or "en").strip().lower(),
    )


def ranking_movement(current_position, previous_position, current_status="found"):
    """Return movement metadata; positive movement means a ranking improved."""
    if current_status == "failed":
        return {"value": None, "label": "Check failed", "direction": "failed"}
    if current_position is not None and previous_position is not None:
        change = previous_position - current_position
        if change > 0:
            return {"value": change, "label": f"Up {change}", "direction": "up"}
        if change < 0:
            return {"value": change, "label": f"Down {abs(change)}", "direction": "down"}
        return {"value": 0, "label": "No change", "direction": "neutral"}
    if current_position is not None:
        return {"value": None, "label": "New", "direction": "new"}
    if previous_position is not None:
        return {"value": None, "label": "Lost", "direction": "lost"}
    return {"value": None, "label": "Not in top 100", "direction": "neutral"}


def _snapshot_date(snapshot):
    return snapshot.created_at.date().isoformat() if snapshot.created_at else None


def _position_page(position):
    if position is None:
        return None
    if position <= 10:
        return 1
    if position <= 20:
        return 2
    return 3


def _ranking_payload(row):
    if not row:
        return None
    return {
        "id": row.id,
        "position": row.position,
        "search_volume": row.search_volume,
        "url": row.url,
        "status": row.check_status,
        "error_message": row.error_message,
    }


def _latest_snapshots(client_id, limit=12):
    return (
        Snapshot.query.filter(
            Snapshot.client_id == client_id,
            Snapshot.status.in_(VALID_SNAPSHOT_STATUSES),
        )
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        .limit(max(1, min(int(limit), 50)))
        .all()
    )


def _build_rows(keywords, snapshots, ranking_rows):
    if not snapshots:
        return []

    snapshot_by_id = {snapshot.id: snapshot for snapshot in snapshots}
    grouped = defaultdict(dict)
    for row in ranking_rows:
        key = ranking_lookup_key(row.keyword, row.location, row.device, row.language, row.competitor_id)
        # Keep the latest stored row if an old provider response duplicated it.
        grouped[key][row.snapshot_id] = row

    latest_snapshot = snapshots[0]
    previous_snapshot = snapshots[1] if len(snapshots) > 1 else None
    result = []
    for keyword in keywords:
        key = ranking_lookup_key(keyword.keyword, keyword.location, keyword.device, keyword.language)
        by_snapshot = grouped.get(key, {})
        latest = by_snapshot.get(latest_snapshot.id)
        previous = by_snapshot.get(previous_snapshot.id) if previous_snapshot else None
        current_position = latest.position if latest else None
        previous_position = previous.position if previous else None
        status = latest.check_status if latest else "not_found"
        movement = ranking_movement(current_position, previous_position, status)
        history = []
        for snapshot in reversed(snapshots):
            row = by_snapshot.get(snapshot.id)
            history.append({
                "snapshot_id": snapshot.id,
                "date": _snapshot_date(snapshot),
                "position": row.position if row else None,
                "status": row.check_status if row else "not_found",
            })
        result.append({
            "keyword_id": keyword.id,
            "keyword": keyword.keyword,
            "location": keyword.location,
            "device": keyword.device,
            "language": keyword.language,
            "priority": keyword.priority,
            "latest_position": current_position,
            "previous_position": previous_position,
            "latest_page": _position_page(current_position),
            "movement": movement["value"],
            "movement_label": movement["label"],
            "movement_direction": movement["direction"],
            "status": status,
            "ranking_url": latest.url if latest else None,
            "search_volume": latest.search_volume if latest else None,
            "latest": _ranking_payload(latest),
            "previous": _ranking_payload(previous),
            "history": history,
        })
    return result


def _matches_filter(row, filter_name):
    if filter_name == "winners":
        return row["movement"] is not None and row["movement"] > 0
    if filter_name == "losers":
        return row["movement"] is not None and row["movement"] < 0
    if filter_name == "page_1":
        return row["latest_page"] == 1
    if filter_name == "page_2":
        return row["latest_page"] == 2
    if filter_name == "not_ranking":
        return row["status"] != "failed" and row["latest_position"] is None
    if filter_name == "check_failed":
        return row["status"] == "failed"
    return True


def get_keyword_movement_data(client_id, *, filter_name="all", search="", location=None,
                              device=None, page=1, per_page=25, history_limit=12):
    """Return keyword movement rows, summary, history, and pagination metadata."""
    filter_name = filter_name if filter_name in VALID_FILTERS else "all"
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(100, int(per_page)))
    except (TypeError, ValueError):
        per_page = 25

    keywords_query = Keyword.query.filter_by(client_id=client_id)
    if location:
        keywords_query = keywords_query.filter(db.func.lower(Keyword.location) == location.strip().lower())
    if device:
        keywords_query = keywords_query.filter(db.func.lower(Keyword.device) == device.strip().lower())
    keywords = keywords_query.order_by(Keyword.keyword.asc(), Keyword.id.asc()).all()
    snapshots = _latest_snapshots(client_id, history_limit)
    snapshot_ids = [snapshot.id for snapshot in snapshots]
    ranking_rows = (
        Ranking.query.filter(
            Ranking.snapshot_id.in_(snapshot_ids),
            Ranking.competitor_id.is_(None),
        ).order_by(Ranking.id.asc()).all()
        if snapshot_ids else []
    )
    rows = _build_rows(keywords, snapshots, ranking_rows)

    search = (search or "").strip().lower()
    if search:
        rows = [row for row in rows if search in (row["keyword"] or "").lower()]
    summary_rows = rows
    summary = {
        "total": len(summary_rows),
        "winners": sum(1 for row in summary_rows if _matches_filter(row, "winners")),
        "losers": sum(1 for row in summary_rows if _matches_filter(row, "losers")),
        "page_1": sum(1 for row in summary_rows if _matches_filter(row, "page_1")),
        "page_2": sum(1 for row in summary_rows if _matches_filter(row, "page_2")),
        "not_ranking": sum(1 for row in summary_rows if _matches_filter(row, "not_ranking")),
        "check_failed": sum(1 for row in summary_rows if _matches_filter(row, "check_failed")),
    }
    rows = [row for row in rows if _matches_filter(row, filter_name)]
    rows.sort(key=lambda row: (row["keyword"] or "").lower())
    total_items = len(rows)
    start = (page - 1) * per_page
    items = rows[start:start + per_page]
    return {
        "summary": summary,
        "items": items,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": (total_items + per_page - 1) // per_page,
        },
        "meta": {
            "latest_snapshot_id": snapshots[0].id if snapshots else None,
            "previous_snapshot_id": snapshots[1].id if len(snapshots) > 1 else None,
            "history_snapshots": [
                {"id": snapshot.id, "date": _snapshot_date(snapshot)} for snapshot in reversed(snapshots)
            ],
        },
    }
