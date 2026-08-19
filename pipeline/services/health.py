import json

from app.models import CrawlIssue, GscMetric, Ranking, Snapshot, db


def _safe_load_notes(snapshot):
    if not snapshot or not snapshot.notes:
        return {}
    try:
        return json.loads(snapshot.notes)
    except json.JSONDecodeError:
        return {}


def compute_health_score(current_snapshot, previous_snapshot=None):
    if not current_snapshot:
        return {
            "score": None,
            "label": "No data",
            "tone": "neutral",
            "summary": "Run an analysis to generate the first health score.",
            "factors": [],
        }

    score = 100
    factors = []

    crawl_count = db.session.query(CrawlIssue).filter_by(snapshot_id=current_snapshot.id).count()
    if crawl_count >= 1000:
        score -= 30
        factors.append("Very high crawl issue count")
    elif crawl_count >= 500:
        score -= 18
        factors.append("High crawl issue count")
    elif crawl_count >= 100:
        score -= 8
        factors.append("Moderate crawl issue count")

    ranking_count, ranked_count, average_position = (
        db.session.query(
            db.func.count(Ranking.id),
            db.func.count(Ranking.position),
            db.func.avg(Ranking.position),
        )
        .filter_by(snapshot_id=current_snapshot.id)
        .one()
    )
    if ranking_count:
        coverage_ratio = ranked_count / ranking_count
        if coverage_ratio == 0:
            score -= 18
            factors.append("Tracked keywords are not ranking yet")
        elif coverage_ratio < 0.5:
            score -= 10
            factors.append("Only a small share of tracked keywords are ranking")

        if ranked_count:
            if average_position <= 10:
                score += 6
                factors.append("Tracked keywords are on page 1 on average")
            elif average_position <= 20:
                score += 2
                factors.append("Tracked keywords are close to page 1 on average")
            elif average_position > 30:
                score -= 8
                factors.append("Tracked keywords are ranking too low on average")

    current_notes = _safe_load_notes(current_snapshot)
    current_gsc_failed = isinstance(current_notes.get("gsc"), str) and current_notes.get("gsc", "").startswith("FAILED")
    rankings_note = current_notes.get("rankings")
    current_rankings_failed = (
        isinstance(rankings_note, str) and rankings_note.startswith("FAILED")
    ) or (
        isinstance(rankings_note, dict) and bool(rankings_note.get("errors"))
    )
    current_report_failed = isinstance(current_notes.get("report"), str) and current_notes.get("report", "").startswith("FAILED")
    if current_gsc_failed or current_rankings_failed or current_report_failed:
        score -= 12
        factors.append("One or more pipeline modules failed in the latest run")

    if previous_snapshot:
        current_clicks = db.session.query(db.func.sum(GscMetric.clicks)).filter_by(snapshot_id=current_snapshot.id).scalar() or 0
        previous_clicks = db.session.query(db.func.sum(GscMetric.clicks)).filter_by(snapshot_id=previous_snapshot.id).scalar() or 0
        current_impressions = db.session.query(db.func.sum(GscMetric.impressions)).filter_by(snapshot_id=current_snapshot.id).scalar() or 0
        previous_impressions = db.session.query(db.func.sum(GscMetric.impressions)).filter_by(snapshot_id=previous_snapshot.id).scalar() or 0

        if previous_clicks > 0:
            click_change = (current_clicks - previous_clicks) / previous_clicks
            if click_change <= -0.2:
                score -= 12
                factors.append("Organic clicks dropped sharply versus the previous snapshot")
            elif click_change >= 0.15:
                score += 6
                factors.append("Organic clicks improved versus the previous snapshot")

        if previous_impressions > 0:
            impression_change = (current_impressions - previous_impressions) / previous_impressions
            if impression_change <= -0.2:
                score -= 6
                factors.append("Organic visibility dropped versus the previous snapshot")
            elif impression_change >= 0.15:
                score += 3
                factors.append("Organic visibility improved versus the previous snapshot")

    score = max(0, min(100, int(round(score))))
    if score >= 80:
        label = "Strong"
        tone = "good"
    elif score >= 60:
        label = "Watch"
        tone = "warn"
    else:
        label = "Critical"
        tone = "bad"

    summary = "Health score reflects crawl quality, tracked keyword coverage, and recent search performance."
    if factors:
        summary = "; ".join(factors[:3])

    return {
        "score": score,
        "label": label,
        "tone": tone,
        "summary": summary,
        "factors": factors,
    }
