"""Turn pipeline diagnostics into concise, actionable audit-status messages."""

from services.pipeline_status import load_notes


STAGE_LABELS = {
    "crawl": "Website crawl",
    "ga4": "Google Analytics (GA4)",
    "gsc": "Google Search Console",
    "rankings": "Keyword rankings",
    "backlinks": "Backlink data",
    "competitor_insights": "Competitor data",
    "report": "AI report",
}


def _short_text(value, fallback="No further technical detail was recorded."):
    text = str(value or "").strip()
    return text[:500] if text else fallback


def _int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _issue(stage, *, status="failed", error=None, notes=None):
    """Build a safe explanation and next action for one pipeline stage."""
    notes = notes or {}
    label = STAGE_LABELS.get(stage, stage.replace("_", " ").title())
    technical_detail = _short_text(error)

    if stage == "rankings":
        ranking = notes.get("rankings") if isinstance(notes.get("rankings"), dict) else {}
        sample_errors = ranking.get("errors") if isinstance(ranking.get("errors"), list) else []
        failed_rows = _int(ranking.get("failed_rows") or ranking.get("error_count"))
        # Pre-hardening snapshots only stored the individual error list.
        # Keep their explanation just as specific as newly-created snapshots.
        if not failed_rows:
            failed_rows = len(sample_errors)
        total_rows = _int(ranking.get("rows"))
        if sample_errors:
            technical_detail = _short_text(sample_errors[0])
        count_text = f"{failed_rows} of {total_rows} checks" if total_rows else "Some checks"
        return {
            "stage": stage,
            "label": label,
            "severity": "warning" if status == "partial" else "danger",
            "title": f"{count_text} could not be verified",
            "detail": (
                "DataForSEO did not return a usable result for these checks. "
                "Confirmed rankings and confirmed ‘Not in Top 100’ results remain valid."
            ),
            "action": "Run a ranking-only check after DataForSEO is available.",
            "technical_detail": technical_detail,
        }
    if stage == "report":
        return {
            "stage": stage,
            "label": label,
            "severity": "warning",
            "title": "The AI report was not generated",
            "detail": "All available audit data was saved; only the narrative AI report is missing.",
            "action": "Check the AI provider configuration, then regenerate the report when available.",
            "technical_detail": technical_detail,
        }
    if stage == "crawl":
        return {
            "stage": stage,
            "label": label,
            "severity": "danger",
            "title": "The website crawl did not complete",
            "detail": "Technical SEO results may be incomplete or unavailable.",
            "action": "Check the project URL and crawl settings, then run the audit again.",
            "technical_detail": technical_detail,
        }
    if stage in {"ga4", "gsc"}:
        return {
            "stage": stage,
            "label": label,
            "severity": "warning",
            "title": f"{label} data could not be collected",
            "detail": "Other audit data was saved and can still be used.",
            "action": "Check the connected Google account and its access permissions, then retry this data source.",
            "technical_detail": technical_detail,
        }
    return {
        "stage": stage,
        "label": label,
        "severity": "warning" if status == "partial" else "danger",
        "title": f"{label} did not complete",
        "detail": "Other successfully collected audit data remains available.",
        "action": "Review the technical detail and retry the affected data source.",
        "technical_detail": technical_detail,
    }


def build_audit_status_summary(snapshot_status, raw_notes):
    """Return one customer-readable status plus precise stage diagnostics.

    ``Snapshot.status`` stays deliberately compact for filtering and durable
    orchestration. This presentation model makes it clear *what* failed,
    *what data remains valid*, and *what action to take* without requiring a
    developer to interpret a generic ``partial`` or ``failed`` badge.
    """
    notes = raw_notes if isinstance(raw_notes, dict) else load_notes(raw_notes)
    stage_results = notes.get("stage_results") if isinstance(notes.get("stage_results"), list) else []
    issues = []
    handled_stages = set()

    for stage_result in stage_results:
        if not isinstance(stage_result, dict):
            continue
        stage = stage_result.get("name")
        status = stage_result.get("status")
        if not stage or status not in {"partial", "failed"}:
            continue
        issues.append(_issue(stage, status=status, error=stage_result.get("error"), notes=notes))
        handled_stages.add(stage)

    # Older snapshots predate structured ``stage_results``. Preserve useful
    # explanations for them as well, instead of returning a mysterious badge.
    for stage in STAGE_LABELS:
        if stage in handled_stages:
            continue
        value = notes.get(stage)
        if isinstance(value, str) and value.startswith("FAILED:"):
            issues.append(_issue(stage, error=value.removeprefix("FAILED:").strip(), notes=notes))

    status = (snapshot_status or "pending").lower()
    if status == "complete":
        return {
            "status": status,
            "css_status": "complete",
            "label": "Completed",
            "headline": "Audit completed successfully",
            "summary": "All selected data sources completed and were saved to this snapshot.",
            "issues": [],
        }
    if status == "partial":
        return {
            "status": status,
            "css_status": "partial",
            "label": "Completed with warnings",
            "headline": "Usable audit data was saved",
            "summary": "Some data sources need attention; the affected items are listed below.",
            "issues": issues or [_issue("report", notes=notes, error="The pipeline marked this audit as partial.")],
        }
    if status == "failed":
        return {
            "status": status,
            "css_status": "failed",
            "label": "Needs attention",
            "headline": "The audit did not complete reliably",
            "summary": "Review the affected stage below before starting another full audit.",
            "issues": issues or [_issue("crawl", notes=notes, error=notes.get("job"))],
        }
    if status == "running":
        return {
            "status": status,
            "css_status": "running",
            "label": "In progress",
            "headline": "Audit is running",
            "summary": "Live progress shows the current stage and completed work.",
            "issues": [],
        }
    return {
        "status": status,
        "css_status": "pending",
        "label": "Queued",
        "headline": "Audit is waiting to start",
        "summary": "The worker will begin this audit when capacity is available.",
        "issues": [],
    }
