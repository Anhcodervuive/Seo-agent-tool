"""
Compares a client's two most recent snapshots and computes deltas.
Answers: is the client improving or declining, and where?
Usage: imported by analyze.py, or run standalone: python3 trends.py <client_id>
"""
import sqlite3, os, sys
from app.models import CrawlIssue, Ga4Metric, GscMetric, Snapshot, db

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "seo_agent.db")

def _two_snapshots(conn, cid):
    rows = conn.execute(
        "SELECT id, run_date FROM snapshots WHERE client_id=? AND status IN ('complete','partial') ORDER BY run_date DESC LIMIT 2",
        (cid,)).fetchall()
    if len(rows) < 2:
        return None, None
    current = rows[0]   # most recent
    previous = rows[1]  # the one before
    return current, previous

def _ga4_sessions(conn, sid):
    r = conn.execute("SELECT SUM(metric_value) FROM ga4_metrics WHERE snapshot_id=? AND metric_name='sessions'", (sid,)).fetchone()
    return r[0] or 0

def _gsc_totals(conn, sid):
    r = conn.execute("SELECT SUM(clicks), SUM(impressions), AVG(position) FROM gsc_metrics WHERE snapshot_id=?", (sid,)).fetchone()
    return {"clicks": r[0] or 0, "impressions": r[1] or 0, "avg_position": round(r[2],1) if r[2] else None}

def _crawl_counts(conn, sid):
    total = conn.execute("SELECT COUNT(*) FROM crawl_issues WHERE snapshot_id=?", (sid,)).fetchone()[0]
    errors = conn.execute("SELECT COUNT(*) FROM crawl_issues WHERE snapshot_id=? AND issue_type='error'", (sid,)).fetchone()[0]
    return {"total": total, "errors": errors}

def _pct(cur, prev):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)

def _keyword_moves(conn, cur_sid, prev_sid):
    # Compare GSC positions per query between snapshots
    cur = {q: p for q, p in conn.execute("SELECT query, position FROM gsc_metrics WHERE snapshot_id=? AND position IS NOT NULL", (cur_sid,)).fetchall()}
    prev = {q: p for q, p in conn.execute("SELECT query, position FROM gsc_metrics WHERE snapshot_id=? AND position IS NOT NULL", (prev_sid,)).fetchall()}
    improved, declined = [], []
    for q in cur:
        if q in prev:
            delta = prev[q] - cur[q]  # positive = moved up (lower position number)
            if delta >= 1:
                improved.append({"query": q, "from": round(prev[q],1), "to": round(cur[q],1), "gain": round(delta,1)})
            elif delta <= -1:
                declined.append({"query": q, "from": round(prev[q],1), "to": round(cur[q],1), "drop": round(-delta,1)})
    improved.sort(key=lambda x: x["gain"], reverse=True)
    declined.sort(key=lambda x: x["drop"], reverse=True)
    return improved[:10], declined[:10]

def compute_trends(conn, cid):
    current, previous = _two_snapshots(conn, cid)
    if not current:
        return None  # not enough snapshots yet
    c_sid, c_date = current
    p_sid, p_date = previous

    cur_sess, prev_sess = _ga4_sessions(conn, c_sid), _ga4_sessions(conn, p_sid)
    cur_gsc, prev_gsc = _gsc_totals(conn, c_sid), _gsc_totals(conn, p_sid)
    cur_crawl, prev_crawl = _crawl_counts(conn, c_sid), _crawl_counts(conn, p_sid)
    improved, declined = _keyword_moves(conn, c_sid, p_sid)

    return {
        "current_date": c_date, "previous_date": p_date,
        "traffic": {
            "sessions_now": int(cur_sess), "sessions_prev": int(prev_sess),
            "change_pct": _pct(cur_sess, prev_sess),
        },
        "search": {
            "clicks_now": cur_gsc["clicks"], "clicks_prev": prev_gsc["clicks"], "clicks_change_pct": _pct(cur_gsc["clicks"], prev_gsc["clicks"]),
            "impressions_now": cur_gsc["impressions"], "impressions_prev": prev_gsc["impressions"], "impressions_change_pct": _pct(cur_gsc["impressions"], prev_gsc["impressions"]),
            "avg_position_now": cur_gsc["avg_position"], "avg_position_prev": prev_gsc["avg_position"],
        },
        "technical": {
            "issues_now": cur_crawl["total"], "issues_prev": prev_crawl["total"],
            "errors_now": cur_crawl["errors"], "errors_prev": prev_crawl["errors"],
        },
        "keywords_improved": improved,
        "keywords_declined": declined,
    }


def compute_trends_from_models(cid):
    rows = (
        db.session.query(Snapshot).filter(Snapshot.client_id == cid, Snapshot.status.in_(["complete", "partial"]))
        .order_by(Snapshot.created_at.desc())
        .limit(2)
        .all()
    )
    if len(rows) < 2:
        return None

    current = rows[0]
    previous = rows[1]

    def ga4_sessions(snapshot_id):
        result = db.session.query(db.func.sum(Ga4Metric.metric_value)).filter(
            Ga4Metric.snapshot_id == snapshot_id,
            Ga4Metric.metric_name == "sessions",
        ).scalar()
        return result or 0

    def gsc_totals(snapshot_id):
        clicks, impressions, avg_position = db.session.query(
            db.func.sum(GscMetric.clicks),
            db.func.sum(GscMetric.impressions),
            db.func.avg(GscMetric.position),
        ).filter(GscMetric.snapshot_id == snapshot_id).one()
        return {
            "clicks": clicks or 0,
            "impressions": impressions or 0,
            "avg_position": round(avg_position, 1) if avg_position else None,
        }

    def crawl_counts(snapshot_id):
        total = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot_id).count()
        errors = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot_id, issue_type="error").count()
        return {"total": total, "errors": errors}

    def pct(cur, prev):
        if not prev:
            return None
        return round((cur - prev) / prev * 100, 1)

    cur_sess, prev_sess = ga4_sessions(current.id), ga4_sessions(previous.id)
    cur_gsc, prev_gsc = gsc_totals(current.id), gsc_totals(previous.id)
    cur_crawl, prev_crawl = crawl_counts(current.id), crawl_counts(previous.id)

    current_positions = {
        row.query: row.position
        for row in db.session.query(GscMetric).filter_by(snapshot_id=current.id).all()
        if row.query and row.position is not None
    }
    previous_positions = {
        row.query: row.position
        for row in db.session.query(GscMetric).filter_by(snapshot_id=previous.id).all()
        if row.query and row.position is not None
    }
    improved, declined = [], []
    for query, position in current_positions.items():
        if query in previous_positions:
            delta = previous_positions[query] - position
            if delta >= 1:
                improved.append({"query": query, "from": round(previous_positions[query], 1), "to": round(position, 1), "gain": round(delta, 1)})
            elif delta <= -1:
                declined.append({"query": query, "from": round(previous_positions[query], 1), "to": round(position, 1), "drop": round(-delta, 1)})
    improved.sort(key=lambda item: item["gain"], reverse=True)
    declined.sort(key=lambda item: item["drop"], reverse=True)

    return {
        "current_date": current.created_at.strftime("%Y-%m-%d %H:%M"),
        "previous_date": previous.created_at.strftime("%Y-%m-%d %H:%M"),
        "traffic": {
            "sessions_now": int(cur_sess),
            "sessions_prev": int(prev_sess),
            "change_pct": pct(cur_sess, prev_sess),
        },
        "search": {
            "clicks_now": cur_gsc["clicks"],
            "clicks_prev": prev_gsc["clicks"],
            "clicks_change_pct": pct(cur_gsc["clicks"], prev_gsc["clicks"]),
            "impressions_now": cur_gsc["impressions"],
            "impressions_prev": prev_gsc["impressions"],
            "impressions_change_pct": pct(cur_gsc["impressions"], prev_gsc["impressions"]),
            "avg_position_now": cur_gsc["avg_position"],
            "avg_position_prev": prev_gsc["avg_position"],
        },
        "technical": {
            "issues_now": cur_crawl["total"],
            "issues_prev": prev_crawl["total"],
            "errors_now": cur_crawl["errors"],
            "errors_prev": prev_crawl["errors"],
        },
        "keywords_improved": improved[:10],
        "keywords_declined": declined[:10],
    }

if __name__ == "__main__":
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    conn = sqlite3.connect(DB)
    import json
    t = compute_trends(conn, cid)
    conn.close()
    print(json.dumps(t, indent=2) if t else "Not enough snapshots to compare yet.")
