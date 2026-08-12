"""Dedicated process that consumes queued and scheduled project audits."""

import argparse
import os
import time
import traceback

from app import create_app
from app.models import AuditJob, Snapshot, db
from services.audit_queue import claim_next_job, enqueue_due_schedules, mark_job_finished, recover_stale_jobs
from services.pipeline_runner import _run_snapshot_job


POLL_SECONDS = max(2, int(os.environ.get("AUDIT_WORKER_POLL_SECONDS", "10")))
STALE_JOB_MINUTES = max(5, int(os.environ.get("AUDIT_WORKER_STALE_JOB_MINUTES", "180")))


def process_one(app):
    """Queue due schedules and run a single waiting job. Returns work count."""
    with app.app_context():
        recovered_count = recover_stale_jobs(STALE_JOB_MINUTES)
        scheduled_count = enqueue_due_schedules()
        job_id = claim_next_job()
        if not job_id:
            return recovered_count + scheduled_count

        job = db.session.get(AuditJob, job_id)
        if not job:
            return recovered_count + scheduled_count
        try:
            _run_snapshot_job(app, job.snapshot_id, job.client_id)
            snapshot = db.session.get(Snapshot, job.snapshot_id)
            if snapshot and snapshot.status == "failed":
                mark_job_finished(job_id, "failed", "Snapshot processing failed.")
            else:
                mark_job_finished(job_id, "completed")
        except Exception as exc:  # Defensive boundary for the worker process.
            traceback.print_exc()
            db.session.rollback()
            mark_job_finished(job_id, "failed", str(exc))
        return recovered_count + scheduled_count + 1


def main():
    parser = argparse.ArgumentParser(description="Run queued SEO audits.")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    args = parser.parse_args()
    app = create_app()
    while True:
        processed = process_one(app)
        if args.once:
            return
        if not processed:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
