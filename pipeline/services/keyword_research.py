"""Durable, project-independent Keyword Research workflow.

This module turns DataForSEO responses into bounded, normalized research runs.
It deliberately does *not* create snapshots or rankings: the only bridge back
to a project is the explicit Add-to-Track action in the Flask route.
"""

from __future__ import annotations

import datetime
import os
import re

from sqlalchemy import or_, select

from app.models import KeywordResearchResult, KeywordResearchRun, db
from services import dataforseo
from services.dataforseo_locations import normalize_google_location


MAX_BULK_KEYWORDS = max(1, min(int(os.environ.get("KEYWORD_RESEARCH_MAX_BULK_KEYWORDS", "250")), 1000))
DISCOVERY_LIMIT = max(10, min(int(os.environ.get("KEYWORD_RESEARCH_DISCOVERY_LIMIT", "100")), 250))
CACHE_MINUTES = max(0, int(os.environ.get("KEYWORD_RESEARCH_CACHE_MINUTES", "60")))
STALE_MINUTES = max(5, int(os.environ.get("KEYWORD_RESEARCH_STALE_MINUTES", "20")))
VALID_MODES = {"single", "bulk"}
VALID_LANGUAGES = {
    "en": "English",
    "vi": "Vietnamese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ja": "Japanese",
    "ko": "Korean",
}


def utcnow():
    return datetime.datetime.utcnow()


def language_options():
    return tuple({"code": code, "name": name} for code, name in VALID_LANGUAGES.items())


def normalize_language(raw_language):
    language = (raw_language or "en").strip().lower()
    if language not in VALID_LANGUAGES:
        raise ValueError("Choose a supported research language.")
    return language


def parse_input_keywords(raw_value, mode):
    """Parse textarea input without interpreting punctuation inside phrases."""
    if mode not in VALID_MODES:
        raise ValueError("Choose single-keyword or bulk-keyword research.")
    chunks = re.split(r"[\r\n,;]+", raw_value or "")
    keywords = []
    seen = set()
    for chunk in chunks:
        keyword = " ".join(chunk.split()).strip()
        if not keyword:
            continue
        if len(keyword) < 3:
            raise ValueError(f'"{keyword}" is too short. Keywords must be at least 3 characters.')
        if len(keyword) > 700:
            raise ValueError(f'"{keyword[:40]}…" is too long. Keywords can be at most 700 characters.')
        normalized = keyword.casefold()
        if normalized not in seen:
            seen.add(normalized)
            keywords.append(keyword)

    if not keywords:
        raise ValueError("Enter at least one keyword.")
    if mode == "single" and len(keywords) != 1:
        raise ValueError("Single Keyword research accepts exactly one keyword.")
    if mode == "bulk" and len(keywords) > MAX_BULK_KEYWORDS:
        raise ValueError(f"Bulk research supports at most {MAX_BULK_KEYWORDS} unique keywords per run.")
    return keywords


def _same_run_inputs(run, *, mode, keywords, location, language):
    return (
        run.mode == mode
        and run.location == location
        and run.language == language
        and list(run.input_keywords or []) == list(keywords)
    )


def create_keyword_research_run(*, created_by_user_id, client_id, mode, keywords, location, language, force_refresh=False):
    """Create a run, optionally reusing the caller's recent complete result."""
    location = normalize_google_location(location)
    language = normalize_language(language)
    keywords = list(keywords)

    if CACHE_MINUTES and not force_refresh:
        cutoff = utcnow() - datetime.timedelta(minutes=CACHE_MINUTES)
        candidates = KeywordResearchRun.query.filter(
            KeywordResearchRun.created_by_user_id == created_by_user_id,
            KeywordResearchRun.status == "complete",
            KeywordResearchRun.created_at >= cutoff,
        ).order_by(KeywordResearchRun.created_at.desc()).limit(25).all()
        for candidate in candidates:
            if _same_run_inputs(candidate, mode=mode, keywords=keywords, location=location, language=language):
                return candidate, True

    run = KeywordResearchRun(
        client_id=client_id,
        created_by_user_id=created_by_user_id,
        mode=mode,
        input_keywords=keywords,
        location=location,
        language=language,
        status="pending",
        progress={
            "phase": "queued",
            "phase_label": "Queued",
            "message": "Waiting for the research worker…",
            "input_count": len(keywords),
            "completed_sections": [],
            "results_saved": 0,
        },
    )
    db.session.add(run)
    db.session.commit()
    return run, False


def _progress(run, phase, label, message, **extra):
    value = dict(run.progress or {})
    value.update({"phase": phase, "phase_label": label, "message": message})
    value.update(extra)
    run.progress = value
    db.session.commit()


def _safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _persist_result(run_id, result_type, row):
    """Store one result after caller-side de-duplication; keep nullable data honest."""
    keyword = " ".join(str(row.get("keyword") or "").split()).strip()
    if not keyword:
        return None
    result = KeywordResearchResult(
        run_id=run_id,
        result_type=result_type,
        keyword=keyword,
        source_types=sorted(set(row.get("source_types") or [])),
        source_rank=_safe_int(row.get("source_rank")),
        search_volume=_safe_int(row.get("search_volume")),
        keyword_difficulty=_safe_int(row.get("keyword_difficulty")),
        cpc=_safe_float(row.get("cpc")),
        competition=_safe_float(row.get("competition")),
        search_intent=(str(row.get("search_intent"))[:64] if row.get("search_intent") else None),
        relevance=_safe_int(row.get("relevance")),
        details=row.get("details") or None,
    )
    db.session.add(result)
    return result


def _error_summary(errors):
    return [
        {
            "section": name.replace("_", " ").title(),
            "message": (error or {}).get("message") or "The data provider did not return this section.",
            "retryable": bool((error or {}).get("retryable")),
        }
        for name, error in (errors or {}).items()
    ]


def _keyword_rows_by_key(run):
    rows = {}
    for row in run.results:
        if row.result_type == "keyword":
            rows[row.keyword.casefold()] = row
    return rows


def run_keyword_research(run_id):
    """Collect and persist one claimed research run. Called only by the worker."""
    run = db.session.get(KeywordResearchRun, run_id)
    if not run or run.status not in {"pending", "running"}:
        return None

    if run.status == "pending":
        run.status = "running"
        run.started_at = utcnow()
        db.session.commit()

    try:
        # A retry is deterministic: replace incomplete old rows instead of
        # duplicating ideas or treating stale data as a fresh result.
        db.session.query(KeywordResearchResult).filter_by(run_id=run.id).delete()
        db.session.commit()

        input_keywords = list(run.input_keywords or [])
        errors = {}
        provider_cost = 0.0
        keyword_rows = {}
        questions = []
        autocomplete = []

        if run.mode == "single":
            _progress(run, "discovering", "Discovering keyword opportunities", "Finding related ideas, Google questions, and autocomplete suggestions…")
            discovery = dataforseo.get_keyword_research_discovery(
                input_keywords[0], run.location, run.language, limit=DISCOVERY_LIMIT,
            )
            provider_cost += float(discovery.get("provider_cost") or 0.0)
            errors.update(discovery.get("errors") or {})
            keyword_rows = {row["keyword"].casefold(): dict(row) for row in discovery.get("keywords") or []}
            seed_key = input_keywords[0].casefold()
            keyword_rows.setdefault(seed_key, {
                "keyword": input_keywords[0],
                "source_types": ["input"],
                "source_rank": 0,
            })
            keyword_rows[seed_key]["source_types"] = sorted(set(keyword_rows[seed_key].get("source_types") or []) | {"input"})
            questions = list(discovery.get("questions") or [])
            autocomplete = list(discovery.get("autocomplete") or [])
            _progress(
                run,
                "enriching",
                "Checking search metrics",
                "Validating current search volume and keyword difficulty…",
                completed_sections=["discovery"],
                discovered_keywords=len(keyword_rows),
                questions_found=len(questions),
                autocomplete_found=len(autocomplete),
            )
        else:
            keyword_rows = {
                keyword.casefold(): {"keyword": keyword, "source_types": ["input"], "source_rank": rank}
                for rank, keyword in enumerate(input_keywords, start=1)
            }
            _progress(
                run,
                "enriching",
                "Checking search metrics",
                f"Checking current search volume and keyword difficulty for {len(keyword_rows)} keywords…",
            )

        metrics = dataforseo.get_keyword_research_metrics(
            [row["keyword"] for row in keyword_rows.values()], run.location, run.language,
        )
        provider_cost += float(metrics.get("provider_cost") or 0.0)
        errors.update(metrics.get("errors") or {})
        metric_values = metrics.get("metrics") or {}
        for key, row in keyword_rows.items():
            row.update({name: value for name, value in (metric_values.get(key) or {}).items() if value is not None})

        _progress(run, "saving", "Saving results", "Saving research results for later review and export…")
        for row in keyword_rows.values():
            _persist_result(run.id, "keyword", row)
        stored_questions = []
        seen_questions = set()
        for row in questions:
            key = str(row.get("keyword") or "").casefold()
            if not key or key in seen_questions:
                continue
            seen_questions.add(key)
            _persist_result(run.id, "question", {**row, "source_types": ["people_also_ask"]})
            stored_questions.append(row)
        stored_autocomplete = []
        seen_autocomplete = set()
        for row in autocomplete:
            key = str(row.get("keyword") or "").casefold()
            if not key or key in seen_autocomplete:
                continue
            seen_autocomplete.add(key)
            _persist_result(run.id, "autocomplete", {**row, "source_types": ["google_autocomplete"]})
            stored_autocomplete.append(row)
        db.session.flush()

        saved_keyword_count = len(keyword_rows)
        metric_count = sum(1 for row in keyword_rows.values() if row.get("search_volume") is not None or row.get("keyword_difficulty") is not None)
        warnings = _error_summary(errors)
        run.provider_cost = provider_cost
        run.summary = {
            "keywords": saved_keyword_count,
            "keywords_with_metrics": metric_count,
            "questions": len(stored_questions),
            "autocomplete": len(stored_autocomplete),
            "warnings": warnings,
            "metrics_source": "DataForSEO Keyword Overview and Bulk Keyword Difficulty",
        }
        run.error_message = "\n".join(f"{warning['section']}: {warning['message']}" for warning in warnings) or None
        run.status = "complete" if not warnings else "partial"
        run.completed_at = utcnow()
        run.progress = {
            "phase": "complete" if run.status == "complete" else "partial",
            "phase_label": "Research complete" if run.status == "complete" else "Research completed with warnings",
            "message": "Saved keyword research is ready to review." if run.status == "complete" else "Saved available results; one or more optional provider sources need attention.",
            "input_count": len(input_keywords),
            "completed_sections": ["metrics"] + (["discovery", "questions", "autocomplete"] if run.mode == "single" else []),
            "results_saved": saved_keyword_count + len(stored_questions) + len(stored_autocomplete),
        }
        db.session.commit()
        print(
            "[keyword-research] completed "
            f"run_id={run.id} status={run.status} keywords={saved_keyword_count} "
            f"questions={len(stored_questions)} autocomplete={len(stored_autocomplete)} warnings={len(warnings)} cost={provider_cost:.4f}",
            flush=True,
        )
        return run
    except Exception as exc:
        db.session.rollback()
        run = db.session.get(KeywordResearchRun, run_id)
        if run:
            has_rows = KeywordResearchResult.query.filter_by(run_id=run.id).first() is not None
            run.status = "partial" if has_rows else "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = utcnow()
            run.progress = {
                "phase": "partial" if has_rows else "failed",
                "phase_label": "Research completed with warnings" if has_rows else "Research failed",
                "message": "Available results were saved, but a later step failed." if has_rows else "No research results could be saved. Please try again later.",
                "input_count": len(run.input_keywords or []),
                "completed_sections": [],
                "results_saved": KeywordResearchResult.query.filter_by(run_id=run.id).count(),
            }
            db.session.commit()
        print(f"[keyword-research] failed run_id={run_id} error={exc}", flush=True)
        return run


def claim_next_keyword_research_run():
    """Claim the oldest waiting run. PostgreSQL locks prevent duplicate workers."""
    try:
        run = db.session.execute(
            select(KeywordResearchRun)
            .where(KeywordResearchRun.status == "pending")
            .order_by(KeywordResearchRun.created_at.asc(), KeywordResearchRun.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if not run:
            db.session.rollback()
            return None
        run.status = "running"
        run.started_at = run.started_at or utcnow()
        run.progress = {
            **(run.progress or {}),
            "phase": "starting",
            "phase_label": "Starting research",
            "message": "Connecting to the keyword data provider…",
        }
        db.session.commit()
        return run.id
    except Exception:
        db.session.rollback()
        raise


def recover_stale_keyword_research_runs(max_age_minutes=STALE_MINUTES):
    cutoff = utcnow() - datetime.timedelta(minutes=max(1, int(max_age_minutes)))
    stale_runs = KeywordResearchRun.query.filter(
        KeywordResearchRun.status == "running",
        or_(
            KeywordResearchRun.updated_at <= cutoff,
            (KeywordResearchRun.updated_at.is_(None) & (KeywordResearchRun.started_at <= cutoff)),
        ),
    ).all()
    for run in stale_runs:
        run.status = "pending"
        run.started_at = None
        run.progress = {
            **(run.progress or {}),
            "phase": "queued",
            "phase_label": "Queued again",
            "message": "The previous worker stopped before research finished; this run was queued again.",
        }
    if stale_runs:
        db.session.commit()
        print(f"[keyword-research] recovered_stale_runs count={len(stale_runs)}", flush=True)
    return len(stale_runs)


def research_queue_health():
    counts = {
        status: count
        for status, count in db.session.query(KeywordResearchRun.status, db.func.count(KeywordResearchRun.id)).group_by(KeywordResearchRun.status).all()
    }
    return {status: int(counts.get(status, 0)) for status in ("pending", "running", "complete", "partial", "failed")}
