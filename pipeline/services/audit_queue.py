"""PostgreSQL-backed queue and recurring schedule helpers for audit jobs."""

import calendar
import datetime
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.models import AuditJob, AuditSchedule, Client, Snapshot, db
from services.crawl_scope import build_crawl_scope
from services.pipeline_stages import normalize_selected_stages


VALID_FREQUENCIES = {"daily", "weekly", "monthly"}
VALID_RUN_TYPES = {"full_audit", "rank_check"}
ACTIVE_JOB_STATUSES = {"pending", "running"}
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_RUN_AT_LOCAL = "02:00"


def retry_backoff_minutes(attempt_count, base_minutes=5):
    """Return bounded exponential backoff for the next retry."""
    return max(1, int(base_minutes)) * (2 ** max(0, int(attempt_count)))


def utcnow():
    return datetime.datetime.utcnow()


def _timezone(name):
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        # Asia/Kolkata is fixed-offset and is the product default. Keep local
        # Windows/dev environments working when the optional tzdata package is
        # not installed; named DST zones still require tzdata/OS zoneinfo.
        if (name or DEFAULT_TIMEZONE) == DEFAULT_TIMEZONE:
            return datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")
        raise ValueError("Choose a valid IANA timezone, for example Asia/Kolkata.") from exc


def _parse_run_at_local(value):
    try:
        return datetime.time.fromisoformat(value or DEFAULT_RUN_AT_LOCAL)
    except ValueError as exc:
        raise ValueError("Choose a valid schedule time.") from exc


def next_scheduled_time(current, frequency, timezone_name=DEFAULT_TIMEZONE, run_at_local=DEFAULT_RUN_AT_LOCAL):
    """Return the next UTC-naive occurrence while keeping the local wall-clock time."""
    tz = _timezone(timezone_name)
    local_time = _parse_run_at_local(run_at_local)
    current_utc = current.replace(tzinfo=datetime.timezone.utc) if current.tzinfo is None else current.astimezone(datetime.timezone.utc)
    local_current = current_utc.astimezone(tz)
    local_candidate = datetime.datetime.combine(local_current.date(), local_time, tzinfo=tz)
    if frequency == "daily":
        if local_candidate <= local_current:
            local_candidate += datetime.timedelta(days=1)
    elif frequency == "monthly":
        month = local_current.month + 1
        year = local_current.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(local_current.day, calendar.monthrange(year, month)[1])
        local_candidate = local_candidate.replace(year=year, month=month, day=day)
    else:
        local_candidate += datetime.timedelta(days=7)
    return local_candidate.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def queue_snapshot_job(
    client, crawl_scope=None, run_type="full_audit", schedule=None, scheduled_for=None,
    commit=True, attempt_count=0, max_attempts=3, available_at=None, retry_of_job_id=None,
    selected_stages=None,
):
    if run_type not in VALID_RUN_TYPES:
        raise ValueError("Choose a valid analysis type.")
    if AuditJob.query.filter(
        AuditJob.client_id == client.id,
        AuditJob.status.in_(ACTIVE_JOB_STATUSES),
    ).first():
        raise ValueError("An analysis is already queued or running for this project.")

    scope = crawl_scope or build_crawl_scope(client)
    selected_stages = ["rankings"] if run_type == "rank_check" else normalize_selected_stages(selected_stages)
    notes = {
        "queued": True,
        "run": {
            "type": run_type,
            "crawl_mode": scope["mode"],
            "crawl_scope": scope,
            "scheduled": bool(schedule),
            "selected_stages": selected_stages,
        },
        "progress": {
            "phase": "queued",
            "phase_label": "Queued",
            "crawled_urls": 0,
            "discovered_urls": 0,
            "pending_urls": 0,
            "ranking_completed": 0,
            "ranking_pending": 0,
            "ranking_total": 0,
            "message": "Waiting for the analysis worker...",
            "updated_at": utcnow().isoformat(timespec="seconds") + "Z",
        },
    }
    snapshot = Snapshot(client_id=client.id, status="pending", notes=json.dumps(notes))
    db.session.add(snapshot)
    db.session.flush()
    job = AuditJob(
        client_id=client.id,
        snapshot_id=snapshot.id,
        schedule_id=schedule.id if schedule else None,
        scheduled_for=scheduled_for,
        run_type=run_type,
        status="pending",
        options={"crawl_scope": scope, "selected_stages": selected_stages},
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        available_at=available_at,
        retry_of_job_id=retry_of_job_id,
    )
    db.session.add(job)
    if commit:
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise ValueError("An analysis is already queued or running for this project.") from exc
    return snapshot, job


def upsert_schedule(client, enabled, frequency, run_type, timezone_name=DEFAULT_TIMEZONE, run_at_local=DEFAULT_RUN_AT_LOCAL):
    """Save one independent recurring schedule for the requested analysis type."""
    if frequency not in VALID_FREQUENCIES:
        raise ValueError("Choose a valid schedule frequency.")
    if run_type not in VALID_RUN_TYPES:
        raise ValueError("Choose a valid scheduled analysis type.")
    schedule = AuditSchedule.query.filter_by(client_id=client.id, run_type=run_type).first()
    if not schedule:
        schedule = AuditSchedule(client_id=client.id)
        db.session.add(schedule)
    timezone_name = (timezone_name or DEFAULT_TIMEZONE).strip()
    _timezone(timezone_name)
    _parse_run_at_local(run_at_local)
    schedule.enabled = bool(enabled)
    schedule.frequency = frequency
    schedule.run_type = run_type
    schedule.timezone = timezone_name
    schedule.run_at_local = run_at_local
    schedule.next_run_at = next_scheduled_time(utcnow(), frequency, timezone_name, run_at_local) if enabled else None
    db.session.commit()
    return schedule


def enqueue_due_schedules():
    """Materialize due schedule records as durable jobs exactly once."""
    now = utcnow()
    schedule_ids = db.session.execute(select(AuditSchedule.id).where(
        AuditSchedule.enabled.is_(True),
        AuditSchedule.next_run_at.isnot(None),
        AuditSchedule.next_run_at <= now,
    ).order_by(AuditSchedule.next_run_at)).scalars().all()
    queued = 0
    for schedule_id in schedule_ids:
        try:
            schedule = db.session.execute(
                select(AuditSchedule).where(AuditSchedule.id == schedule_id).with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if not schedule or not schedule.enabled or not schedule.next_run_at or schedule.next_run_at > now:
                db.session.rollback()
                continue
            client = db.session.get(Client, schedule.client_id)
            if not client or not client.active:
                schedule.next_run_at = next_scheduled_time(now, schedule.frequency, schedule.timezone, schedule.run_at_local)
                db.session.commit()
                continue
            if AuditJob.query.filter(AuditJob.client_id == client.id, AuditJob.status.in_(ACTIVE_JOB_STATUSES)).first():
                db.session.rollback()
                continue
            occurrence = schedule.next_run_at
            queue_snapshot_job(client, run_type=schedule.run_type, schedule=schedule, scheduled_for=occurrence, commit=False)
            schedule.last_run_at = now
            schedule.next_run_at = next_scheduled_time(now, schedule.frequency, schedule.timezone, schedule.run_at_local)
            db.session.commit()
        except (IntegrityError, ValueError):
            db.session.rollback()
            continue
        queued += 1
    return queued


def recover_stale_jobs(max_age_minutes=60):
    """Return abandoned running jobs to the queue after an unexpected worker exit."""
    cutoff = utcnow() - datetime.timedelta(minutes=max(1, int(max_age_minutes)))
    stale_jobs = AuditJob.query.filter(
        AuditJob.status == "running",
        AuditJob.started_at.isnot(None),
        or_(
            AuditJob.heartbeat_at <= cutoff,
            and_(AuditJob.heartbeat_at.is_(None), AuditJob.started_at <= cutoff),
        ),
    ).all()
    for job in stale_jobs:
        job.status = "pending"
        job.started_at = None
        job.heartbeat_at = None
        job.error_message = "Recovered after the previous worker stopped before completion."
    if stale_jobs:
        db.session.commit()
    return len(stale_jobs)


def claim_next_job():
    """Atomically claim one job; SKIP LOCKED makes multiple workers safe."""
    try:
        job = db.session.execute(
            select(AuditJob)
            .where(AuditJob.status == "pending", (AuditJob.available_at.is_(None)) | (AuditJob.available_at <= utcnow()))
            .order_by(AuditJob.queued_at, AuditJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if not job:
            db.session.rollback()
            return None
        job.status = "running"
        job.started_at = utcnow()
        job.heartbeat_at = job.started_at
        job.available_at = None
        job.attempt_count += 1
        db.session.commit()
        return job.id
    except Exception:
        db.session.rollback()
        raise


def mark_job_finished(job_id, status, error_message=None):
    job = db.session.get(AuditJob, job_id)
    if not job:
        return
    job.status = status
    job.error_message = error_message
    job.completed_at = utcnow()
    job.heartbeat_at = None
    db.session.commit()


def retry_failed_job(job_id, error_message, retry_delay_minutes=5):
    """Create a clean snapshot for a transient failure, with bounded backoff."""
    job = db.session.get(AuditJob, job_id)
    if not job:
        return None
    if job.attempt_count >= job.max_attempts:
        mark_job_finished(job_id, "failed", error_message)
        return None
    client = db.session.get(Client, job.client_id)
    if not client or not client.active:
        mark_job_finished(job_id, "failed", error_message)
        return None

    job.status = "failed"
    job.error_message = error_message
    job.completed_at = utcnow()
    job.heartbeat_at = None
    retry_number = job.attempt_count + 1
    delay = datetime.timedelta(minutes=retry_backoff_minutes(retry_number - 1, retry_delay_minutes))
    retry_snapshot, retry_job = queue_snapshot_job(
        client,
        crawl_scope=(job.options or {}).get("crawl_scope"),
        run_type=job.run_type,
        selected_stages=(job.options or {}).get("selected_stages"),
        schedule=job.schedule,
        commit=False,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        available_at=utcnow() + delay,
        retry_of_job_id=job.id,
    )
    del retry_snapshot  # The durable retry job owns the replacement snapshot.
    db.session.commit()
    return retry_job


def touch_job_heartbeat(job_id):
    job = db.session.get(AuditJob, job_id)
    if job and job.status == "running":
        job.heartbeat_at = utcnow()
        db.session.commit()


def queue_health():
    """Small operational snapshot for worker logs and alerting."""
    now = utcnow()
    pending = db.session.scalar(select(func.count()).select_from(AuditJob).where(AuditJob.status == "pending")) or 0
    running = db.session.scalar(select(func.count()).select_from(AuditJob).where(AuditJob.status == "running")) or 0
    failed = db.session.scalar(select(func.count()).select_from(AuditJob).where(AuditJob.status == "failed")) or 0
    overdue = db.session.scalar(
        select(func.count()).select_from(AuditSchedule).where(
            AuditSchedule.enabled.is_(True),
            AuditSchedule.next_run_at.isnot(None),
            AuditSchedule.next_run_at <= now,
        )
    ) or 0
    return {"pending": pending, "running": running, "failed": failed, "overdue_schedules": overdue}
