"""Presentation-safe state for the live audit progress card.

The worker records factual progress in ``Snapshot.notes``.  This module turns
those facts into short, customer-facing labels for the web UI without making
the Flask route or the browser infer provider state on their own.
"""

from __future__ import annotations


TERMINAL_SNAPSHOT_STATUSES = {"complete", "partial", "failed"}
TERMINAL_PROGRESS_PHASES = TERMINAL_SNAPSHOT_STATUSES

STAGE_LABELS = {
    "crawl": "Crawling website",
    "ga4": "Collecting GA4 data",
    "gsc": "Collecting Search Console data",
    "backlinks": "Collecting backlink data",
    "competitor_insights": "Collecting competitor data",
    "rankings": "Checking keyword rankings",
    "report": "Generating report",
    "preparing": "Preparing audit",
    "complete": "Audit complete",
    "partial": "Audit completed with issues",
    "failed": "Audit failed",
}


def _number(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _fraction(numerator, denominator):
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _ranking_copy(state, submitted, completed, total, pending):
    """Return an honest provider-state label and supporting detail."""
    if state == "not_selected":
        return "Not selected for this audit", "Keyword ranking checks were not requested."
    if state == "not_configured":
        return "No tracked keywords configured", "Add keywords to enable ranking checks."
    if state == "preparing":
        return "Preparing DataForSEO tasks", "The audit is preparing keyword checks."
    if state == "processing":
        return (
            f"{submitted} check{'s' if submitted != 1 else ''} processing in DataForSEO",
            "Results will be collected after the independent audit stages finish.",
        )
    if state == "submitted":
        return (
            f"{submitted} check{'s' if submitted != 1 else ''} submitted to DataForSEO",
            "Waiting to collect the available ranking results.",
        )
    if state == "collecting":
        return (
            "Collecting ranking results from DataForSEO",
            f"{completed} of {total} results collected · {pending} remaining.",
        )
    if state == "timed_out":
        return (
            "Ranking result wait timed out",
            f"{completed} of {total} results were saved; unavailable checks are marked for attention.",
        )
    if state == "submission_failed":
        return "Unable to submit ranking checks", "The audit saved the provider diagnostic for follow-up."
    if state == "complete_with_issues":
        return (
            "Ranking results collected with issues",
            f"{completed} of {total} checks completed; review unavailable checks in Audit History.",
        )
    if state == "complete":
        return "Ranking results collected", f"{completed} of {total} checks completed."

    # Snapshots created before the explicit provider state existed still have
    # useful raw counters. Keep their progress card meaningful after deploy.
    if total:
        return "Ranking progress", f"{completed} of {total} results collected · {pending} remaining."
    return "Ranking checks not started", "No ranking tasks have been submitted yet."


def _workflow_presentation(progress, snapshot_status):
    phase = progress.get("phase") or "preparing"
    total = _number(progress.get("workflow_total_stages"))
    finished = min(_number(progress.get("workflow_finished_stages")), total) if total else 0
    position = _number(progress.get("workflow_current_stage_position"))
    current_stage = progress.get("workflow_current_stage") or phase
    current_label = progress.get("workflow_current_stage_label") or STAGE_LABELS.get(current_stage) or progress.get("phase_label") or "Analysis in progress"
    terminal = snapshot_status in TERMINAL_SNAPSHOT_STATUSES or phase in TERMINAL_PROGRESS_PHASES

    if terminal:
        percent = 100
        summary = "All audit stages finished"
        detail = f"{total or finished} of {total or finished} audit stages finished"
    elif not total:
        # Compatibility path for a live snapshot created by an older worker.
        crawl_fraction = _fraction(
            _number(progress.get("crawled_urls")),
            _number(progress.get("discovered_urls")),
        ) if phase == "crawl" else 0.0
        ranking_fraction = _fraction(
            _number(progress.get("ranking_completed")),
            _number(progress.get("ranking_total")),
        ) if phase == "rankings" else 0.0
        percent = round(max(crawl_fraction, ranking_fraction) * 100, 2)
        summary = current_label
        detail = "Live stage progress"
    else:
        stage_fraction = 0.0
        # A partial stage contribution is used only while that stage is still
        # active. Once it is finished, ``finished`` already includes it.
        if finished < position:
            if phase == "crawl":
                stage_fraction = _fraction(
                    _number(progress.get("crawled_urls")),
                    _number(progress.get("discovered_urls")),
                )
            elif phase == "rankings" and progress.get("ranking_state") == "collecting":
                stage_fraction = _fraction(
                    _number(progress.get("ranking_completed")),
                    _number(progress.get("ranking_total")),
                )
        percent = round(min(1.0, (finished + stage_fraction) / total) * 100, 2)
        if position:
            summary = f"Stage {min(max(position, 1), total)} of {total} · {current_label}"
        else:
            summary = f"Preparing {total} audit stage{'s' if total != 1 else ''}"
        detail = f"{finished} of {total} audit stages finished"

    return {
        "summary": summary,
        "detail": detail,
        "percent": percent,
        "current_stage": current_stage,
        "current_label": current_label,
        "finished_stages": finished,
        "total_stages": total,
    }


def build_analysis_progress_presentation(progress, snapshot_status):
    """Build UI copy and bounded percentages from persisted audit progress."""
    progress = progress if isinstance(progress, dict) else {}
    crawled = _number(progress.get("crawled_urls"))
    discovered = _number(progress.get("discovered_urls"))
    pending_urls = _number(progress.get("pending_urls"))
    ranking_completed = _number(progress.get("ranking_completed"))
    ranking_total = _number(progress.get("ranking_total"))
    ranking_pending = _number(progress.get("ranking_pending"))
    ranking_submitted = _number(progress.get("ranking_submitted"))
    ranking_state = progress.get("ranking_state") or "unknown"
    ranking_label, ranking_detail = _ranking_copy(
        ranking_state,
        ranking_submitted,
        ranking_completed,
        ranking_total,
        ranking_pending,
    )

    return {
        "workflow": _workflow_presentation(progress, snapshot_status),
        "crawl": {
            "crawled": crawled,
            "discovered": discovered,
            "pending": pending_urls,
            "detail": f"{pending_urls} pending · {discovered} discovered",
        },
        "rankings": {
            "state": ranking_state,
            "label": ranking_label,
            "detail": ranking_detail,
            "submitted": ranking_submitted,
            "completed": ranking_completed,
            "pending": ranking_pending,
            "total": ranking_total,
        },
    }
