"""PostgreSQL-backed queue and recurring schedule helpers for audit jobs."""

import calendar
import datetime
import json

from sqlalchemy import select

from app.models import AuditJob, AuditSchedule, Client, Snapshot, db
from services.crawl_scope import build_crawl_scope


VALID_FREQUENCIES = {"daily", "weekly", "monthly"}
VALID_RUN_TYPES = {"full_audit", "rank_check"}
ACTIVE_JOB_STATUSES = {"pending", "running"}


def utcnow():
    return datetime.datetime.utcnow()


def next_scheduled_time(current, frequency):
    if frequency == "daily":
        return current + datetime.timedelta(days=1)
    if frequency == "monthly":
        month = current.month + 1
        year = current.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    return current + datetime.timedelta(days=7)


def queue_snapshot_job(client, crawl_scope=None, run_type="full_audit", schedule=None):
    if run_type not in VALID_RUN_TYPES:
        raise ValueError("Choose a valid analysis type.")
    if AuditJob.query.filter(
        AuditJob.client_id == client.id,
        AuditJob.status.in_(ACTIVE_JOB_STATUSES),
    ).first():
        raise ValueError("An analysis is already queued or running for this project.")

    scope = crawl_scope or build_crawl_scope(client)
    notes = {
        "queued": True,
        "run": {
            "type": run_type,
            "crawl_mode": scope["mode"],
            "crawl_scope": scope,
            "scheduled": bool(schedule),
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
        run_type=run_type,
        status="pending",
        options={"crawl_scope": scope},
    )
    db.session.add(job)
    db.session.commit()
    return snapshot, job


def upsert_schedule(client, enabled, frequency, run_type):
    if frequency not in VALID_FREQUENCIES:
        raise ValueError("Choose a valid schedule frequency.")
    if run_type not in VALID_RUN_TYPES:
        raise ValueError("Choose a valid scheduled analysis type.")
    schedule = AuditSchedule.query.filter_by(client_id=client.id).first()
    if not schedule:
        schedule = AuditSchedule(client_id=client.id)
        db.session.add(schedule)
    schedule.enabled = bool(enabled)
    schedule.frequency = frequency
    schedule.run_type = run_type
    schedule.next_run_at = next_scheduled_time(utcnow(), frequency) if enabled else None
    db.session.commit()
    return schedule


def enqueue_due_schedules():
    """Materialize due schedule records as durable jobs exactly once."""
    now = utcnow()
    schedules = AuditSchedule.query.filter(
        AuditSchedule.enabled.is_(True),
        AuditSchedule.next_run_at.isnot(None),
        AuditSchedule.next_run_at <= now,
    ).order_by(AuditSchedule.next_run_at).all()
    queued = 0
    for schedule in schedules:
        client = db.session.get(Client, schedule.client_id)
        if not client or not client.active:
            schedule.next_run_at = next_scheduled_time(now, schedule.frequency)
            db.session.commit()
            continue
        if AuditJob.query.filter(
            AuditJob.client_id == client.id,
            AuditJob.status.in_(ACTIVE_JOB_STATUSES),
        ).first():
            continue
        try:
            queue_snapshot_job(client, run_type=schedule.run_type, schedule=schedule)
        except ValueError:
            continue
        schedule.last_run_at = now
        schedule.next_run_at = next_scheduled_time(now, schedule.frequency)
        db.session.commit()
        queued += 1
    return queued


def recover_stale_jobs(max_age_minutes=60):
    """Return abandoned running jobs to the queue after an unexpected worker exit."""
    cutoff = utcnow() - datetime.timedelta(minutes=max(1, int(max_age_minutes)))
    stale_jobs = AuditJob.query.filter(
        AuditJob.status == "running",
        AuditJob.started_at.isnot(None),
        AuditJob.started_at <= cutoff,
    ).all()
    for job in stale_jobs:
        job.status = "pending"
        job.started_at = None
        job.error_message = "Recovered after the previous worker stopped before completion."
    if stale_jobs:
        db.session.commit()
    return len(stale_jobs)


def claim_next_job():
    """Atomically claim one job; SKIP LOCKED makes multiple workers safe."""
    try:
        job = db.session.execute(
            select(AuditJob)
            .where(AuditJob.status == "pending")
            .order_by(AuditJob.queued_at, AuditJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if not job:
            db.session.rollback()
            return None
        job.status = "running"
        job.started_at = utcnow()
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
    db.session.commit()
