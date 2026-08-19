"""Versioned, explainable project-health scoring built from stored data."""

from datetime import datetime

from sqlalchemy import func

from app.models import BacklinkHistory, CrawlIssue, CrawlPage, Ga4DailyMetric, GscDailyMetric, HealthScore, Ranking, Snapshot, db
from services.metric_comparison import compare_daily_windows, percent_change


ALGORITHM_VERSION = "v2"
PILLAR_WEIGHTS = {"technical": 35, "organic": 30, "keywords": 20, "backlinks": 15}


def _tone(score):
    if score is None:
        return "No data", "neutral"
    if score >= 80:
        return "Strong", "good"
    if score >= 60:
        return "Watch", "warn"
    return "Critical", "bad"


def _issue_weight(issue):
    text = " ".join(filter(None, (issue.issue_type, issue.category, issue.issue))).lower()
    if any(term in text for term in ("critical", "error", "404", "5xx", "broken", "blocked")):
        return 5
    if any(term in text for term in ("warning", "duplicate", "missing", "redirect")):
        return 2
    return 0.5


def _technical_component(snapshot):
    pages = db.session.query(func.count(CrawlPage.id)).filter_by(snapshot_id=snapshot.id).scalar() or 0
    if not pages:
        return None
    issues = CrawlIssue.query.filter_by(snapshot_id=snapshot.id).all()
    density = sum(_issue_weight(issue) for issue in issues) / max(1, pages)
    score = 100 if density <= 0.25 else 90 if density <= 1 else 75 if density <= 3 else 55 if density <= 7 else 30
    return {
        "score": score,
        "weight": PILLAR_WEIGHTS["technical"],
        "coverage": 1,
        "metrics": {"pages": int(pages), "issues": len(issues), "weighted_issue_density": round(density, 2)},
        "summary": f"{len(issues)} issues across {pages} crawled pages.",
    }


def _bounded_change_score(change):
    """Maps -30% .. +30% change to a neutral 50-centered score."""
    if change is None:
        return None
    return max(0, min(100, round(50 + (change * 166.67))))


def _organic_component(snapshot):
    anchor = snapshot.created_at.date()
    ga4 = compare_daily_windows(Ga4DailyMetric, snapshot.client_id, ("sessions",), end_date=anchor)
    gsc = compare_daily_windows(GscDailyMetric, snapshot.client_id, ("clicks", "impressions"), end_date=anchor)
    scores, metrics, coverage = [], {}, []
    if ga4.get("available") and ga4["coverage"] >= 0.7:
        change = percent_change(ga4["current"]["sessions"], ga4["previous"]["sessions"])
        scores.append((_bounded_change_score(change), 0.45))
        coverage.append(ga4["coverage"])
        metrics["ga4_sessions_change"] = change
    if gsc.get("available") and gsc["coverage"] >= 0.7:
        click_change = percent_change(gsc["current"]["clicks"], gsc["previous"]["clicks"])
        scores.append((_bounded_change_score(click_change), 0.40))
        coverage.append(gsc["coverage"])
        metrics["gsc_clicks_change"] = click_change
        current_ctr = gsc["current"]["clicks"] / gsc["current"]["impressions"] if gsc["current"]["impressions"] else None
        previous_ctr = gsc["previous"]["clicks"] / gsc["previous"]["impressions"] if gsc["previous"]["impressions"] else None
        ctr_change = percent_change(current_ctr, previous_ctr)
        if ctr_change is not None:
            scores.append((_bounded_change_score(ctr_change), 0.15))
            metrics["gsc_ctr_change"] = ctr_change
    if not scores:
        return None
    total_weight = sum(weight for _, weight in scores)
    return {
        "score": round(sum(value * weight for value, weight in scores) / total_weight),
        "weight": PILLAR_WEIGHTS["organic"],
        "coverage": round(sum(coverage) / len(coverage), 3),
        "metrics": {key: round(value, 4) if value is not None else None for key, value in metrics.items()},
        "summary": "Two equal 30-day windows of stored GA4/GSC daily data.",
    }


def _keyword_component(snapshot):
    total, ranked, average_position = (
        db.session.query(func.count(Ranking.id), func.count(Ranking.position), func.avg(Ranking.position))
        .filter(Ranking.snapshot_id == snapshot.id, Ranking.competitor_id.is_(None))
        .one()
    )
    total, ranked = int(total or 0), int(ranked or 0)
    if not total:
        return None
    top_ten = (
        db.session.query(func.count(Ranking.id))
        .filter(Ranking.snapshot_id == snapshot.id, Ranking.competitor_id.is_(None), Ranking.position <= 10)
        .scalar() or 0
    )
    coverage = ranked / total
    avg_score = 100 if average_position and average_position <= 10 else 70 if average_position and average_position <= 20 else 40 if average_position and average_position <= 30 else 15
    score = (coverage * 45) + ((top_ten / total) * 30) + (avg_score * 0.25)
    return {
        "score": round(score), "weight": PILLAR_WEIGHTS["keywords"], "coverage": round(coverage, 3),
        "metrics": {"tracked": total, "ranked": ranked, "top_10": int(top_ten), "average_position": round(float(average_position), 2) if average_position else None},
        "summary": "Project keyword rows only; competitor rankings are excluded.",
    }


def _backlink_component(snapshot, previous_snapshot):
    current = BacklinkHistory.query.filter_by(snapshot_id=snapshot.id, competitor_id=None).first()
    if not current:
        return None
    metrics = {"referring_domains": current.referring_domains or 0, "total_backlinks": current.total_backlinks or 0, "new_backlinks": current.new_backlinks or 0, "lost_backlinks": current.lost_backlinks or 0}
    previous = BacklinkHistory.query.filter_by(snapshot_id=previous_snapshot.id, competitor_id=None).first() if previous_snapshot else None
    if previous and previous.referring_domains:
        rd_change = percent_change(current.referring_domains or 0, previous.referring_domains)
        metrics["referring_domain_change"] = round(rd_change, 4) if rd_change is not None else None
        score, summary = _bounded_change_score(rd_change), "Referring-domain movement versus the preceding completed audit."
    else:
        score, summary = (60 if (current.referring_domains or 0) else 40), "Baseline backlink coverage; a second completed audit enables movement scoring."
    return {"score": score, "weight": PILLAR_WEIGHTS["backlinks"], "coverage": 1, "metrics": metrics, "summary": summary}


def calculate_health_score(snapshot, previous_snapshot=None):
    if not snapshot:
        return {"score": None, "label": "No data", "tone": "neutral", "confidence": 0, "components": {}, "factors": [], "summary": "Run a full crawl to generate the first health score."}
    components = {"technical": _technical_component(snapshot), "organic": _organic_component(snapshot), "keywords": _keyword_component(snapshot), "backlinks": _backlink_component(snapshot, previous_snapshot)}
    available = {name: component for name, component in components.items() if component is not None}
    active_weight = sum(component["weight"] for component in available.values())
    if not active_weight:
        return {"score": None, "label": "No data", "tone": "neutral", "confidence": 0, "components": components, "factors": [], "summary": "This snapshot does not contain enough stored data for a score."}
    score = round(sum(component["score"] * component["weight"] for component in available.values()) / active_weight)
    confidence = round(sum(component["weight"] * component.get("coverage", 1) for component in available.values()))
    label, tone = _tone(score)
    factors = [f"{name.title()} needs attention: {component['summary']}" for name, component in available.items() if component["score"] < 60]
    if not factors:
        factors.append("Available project health pillars are stable.")
    return {"score": score, "label": label, "tone": tone, "confidence": confidence, "components": components, "factors": factors, "summary": "Weighted technical, organic, keyword, and backlink health. Missing pillars are excluded, not scored as zero.", "algorithm_version": ALGORITHM_VERSION}


def _previous_completed_snapshot(snapshot):
    return (Snapshot.query.filter(Snapshot.client_id == snapshot.client_id, Snapshot.status.in_(("complete", "partial")), Snapshot.created_at < snapshot.created_at).order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).first())


def persist_health_score(snapshot):
    """Calculate and upsert a score only for snapshots that actually crawled pages."""
    if not snapshot or not db.session.query(CrawlPage.id).filter_by(snapshot_id=snapshot.id).first():
        return None
    calculated = calculate_health_score(snapshot, _previous_completed_snapshot(snapshot))
    record = HealthScore.query.filter_by(snapshot_id=snapshot.id).first()
    if not record:
        record = HealthScore(client_id=snapshot.client_id, snapshot_id=snapshot.id)
        db.session.add(record)
    for key in ("score", "label", "tone", "confidence", "components", "factors", "algorithm_version"):
        setattr(record, key, calculated.get(key))
    record.calculated_at = datetime.utcnow()
    db.session.commit()
    return record


def serialize_health_score(record):
    if not record:
        return calculate_health_score(None)
    return {"score": record.score, "label": record.label, "tone": record.tone, "confidence": record.confidence, "components": record.components or {}, "factors": record.factors or [], "summary": "Weighted technical, organic, keyword, and backlink health. Missing pillars are excluded, not scored as zero.", "algorithm_version": record.algorithm_version, "snapshot_id": record.snapshot_id, "calculated_at": record.calculated_at.isoformat() if record.calculated_at else None}


def get_latest_health_score(client_id):
    return HealthScore.query.filter_by(client_id=client_id).order_by(HealthScore.calculated_at.desc(), HealthScore.id.desc()).first()


def compute_health_score(current_snapshot, previous_snapshot=None):
    """Compatibility entry point for callers that need an unpersisted calculation."""
    return calculate_health_score(current_snapshot, previous_snapshot)
