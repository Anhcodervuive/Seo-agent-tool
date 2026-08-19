"""Cursor-paginated project audit history queries."""

import json
from datetime import datetime

from sqlalchemy import and_, or_

from app.models import Ranking, Snapshot, db


DEFAULT_HISTORY_PAGE_SIZE = 10
MAX_HISTORY_PAGE_SIZE = 25


def _parse_cursor(value):
    if not value:
        return None
    try:
        timestamp, snapshot_id = value.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), int(snapshot_id)
    except (TypeError, ValueError):
        return None


def _encode_cursor(snapshot):
    return f"{snapshot.created_at.isoformat()}|{snapshot.id}"


def _parse_notes(snapshot):
    try:
        value = json.loads(snapshot.notes) if snapshot.notes else {}
    except json.JSONDecodeError:
        value = {"raw": snapshot.notes}
    return value if isinstance(value, dict) else {"raw": snapshot.notes}


def get_history_page(client_id, *, cursor=None, limit=DEFAULT_HISTORY_PAGE_SIZE):
    """Fetch one audit-history page without loading a project's full history."""
    try:
        limit = max(1, min(int(limit), MAX_HISTORY_PAGE_SIZE))
    except (TypeError, ValueError):
        limit = DEFAULT_HISTORY_PAGE_SIZE

    query = Snapshot.query.filter(Snapshot.client_id == client_id)
    decoded_cursor = _parse_cursor(cursor)
    if decoded_cursor:
        created_at, snapshot_id = decoded_cursor
        query = query.filter(or_(
            Snapshot.created_at < created_at,
            and_(Snapshot.created_at == created_at, Snapshot.id < snapshot_id),
        ))
    rows = query.order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    snapshots = rows[:limit]
    snapshot_ids = [snapshot.id for snapshot in snapshots]
    keyword_counts = dict(
        db.session.query(Ranking.snapshot_id, db.func.count(Ranking.id))
        .filter(Ranking.snapshot_id.in_(snapshot_ids), Ranking.competitor_id.is_(None))
        .group_by(Ranking.snapshot_id)
        .all()
    ) if snapshot_ids else {}
    return {
        "snapshots": snapshots,
        "parsed_notes": {snapshot.id: _parse_notes(snapshot) for snapshot in snapshots},
        "snapshot_keyword_counts": keyword_counts,
        "next_cursor": _encode_cursor(snapshots[-1]) if has_more and snapshots else None,
        "has_more": has_more,
        "total_count": Snapshot.query.filter_by(client_id=client_id).count(),
    }
