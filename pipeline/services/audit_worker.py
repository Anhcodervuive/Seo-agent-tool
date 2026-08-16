"""Dedicated process that consumes queued and scheduled project audits."""

import argparse
import os
import threading
import time
import traceback

from app import create_app
from app.models import AuditJob, Snapshot, db
from services.audit_queue import claim_next_job, enqueue_due_schedules, mark_job_finished, queue_health, recover_stale_jobs, retry_failed_job, touch_job_heartbeat
from services.pipeline_runner import _run_snapshot_job


POLL_SECONDS = max(2, int(os.environ.get("AUDIT_WORKER_POLL_SECONDS", "10")))
STALE_JOB_MINUTES = max(5, int(os.environ.get("AUDIT_WORKER_STALE_JOB_MINUTES", "180")))
HEARTBEAT_SECONDS = max(15, int(os.environ.get("AUDIT_WORKER_HEARTBEAT_SECONDS", "60")))
RETRY_DELAY_MINUTES = max(1, int(os.environ.get("AUDIT_WORKER_RETRY_DELAY_MINUTES", "5")))
HEALTH_LOG_SECONDS = max(30, int(os.environ.get("AUDIT_WORKER_HEALTH_LOG_SECONDS", "300")))


def _log(message):
    """Write worker lifecycle messages directly to Docker's live logs."""
    print(f"[audit-worker] {message}", flush=True)


def _heartbeat_loop(app, job_id, stop_event):
    while not stop_event.wait(HEARTBEAT_SECONDS):
        with app.app_context():
            touch_job_heartbeat(job_id)


def process_one(app):
    """Queue due schedules and run a single waiting job. Returns work count."""
    with app.app_context():
        recovered_count = recover_stale_jobs(STALE_JOB_MINUTES)
        scheduled_count = enqueue_due_schedules()
        if recovered_count or scheduled_count:
            _log(f"queue maintenance: recovered={recovered_count}, scheduled={scheduled_count}")
        job_id = claim_next_job()
        if not job_id:
            return recovered_count + scheduled_count

        job = db.session.get(AuditJob, job_id)
        if not job:
            _log(f"claimed job #{job_id}, but it no longer exists")
            return recovered_count + scheduled_count
        try:
            _log(f"starting job #{job_id} for snapshot #{job.snapshot_id}, project #{job.client_id}")
            stop_heartbeat = threading.Event()
            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop, args=(app, job_id, stop_heartbeat), daemon=True,
            )
            heartbeat_thread.start()
            try:
                _run_snapshot_job(app, job.snapshot_id, job.client_id)
            finally:
                stop_heartbeat.set()
                heartbeat_thread.join(timeout=HEARTBEAT_SECONDS + 5)
            snapshot = db.session.get(Snapshot, job.snapshot_id)
            if snapshot and snapshot.status == "failed":
                retry = retry_failed_job(job_id, "Snapshot processing failed.", RETRY_DELAY_MINUTES)
                _log(f"job #{job_id} finished: failed" + (f"; retry job #{retry.id} queued" if retry else ""))
            else:
                mark_job_finished(job_id, "completed")
                _log(f"job #{job_id} finished: {snapshot.status if snapshot else 'completed'}")
        except Exception as exc:  # Defensive boundary for the worker process.
            _log(f"job #{job_id} crashed: {exc}")
            traceback.print_exc()
            db.session.rollback()
            retry = retry_failed_job(job_id, str(exc), RETRY_DELAY_MINUTES)
            if retry:
                _log(f"retry job #{retry.id} queued after worker error")
        return recovered_count + scheduled_count + 1


def main():
    parser = argparse.ArgumentParser(description="Run queued SEO audits.")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    args = parser.parse_args()
    app = create_app()
    _log(f"started; poll interval={POLL_SECONDS}s, stale job threshold={STALE_JOB_MINUTES}m")
    next_health_log = time.monotonic()
    while True:
        processed = process_one(app)
        if time.monotonic() >= next_health_log:
            with app.app_context():
                _log(f"health: {queue_health()}")
            next_health_log = time.monotonic() + HEALTH_LOG_SECONDS
        if args.once:
            return
        if not processed:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
