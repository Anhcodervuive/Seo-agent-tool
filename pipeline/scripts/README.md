# Script entry points

The following scripts are retained for backwards compatibility only:

- `run_snapshot.py`
- `run_client.py`
- `queue_run.py`

They use the original SQLite schema and are not part of the current production
pipeline. Production and scheduled execution must use:

```text
python -m services.audit_worker
```

The current pipeline uses Flask-SQLAlchemy, PostgreSQL, durable `AuditJob`
records, retries, heartbeats and recurring schedules. Do not add new features
to the SQLite scripts; migrate callers to `services.audit_worker` instead.

## Daily trend operational commands

The following commands use the current Flask-SQLAlchemy/PostgreSQL pipeline:

- `backfill_daily_trends.py` manually fills one project's missing daily GA4/GSC
  history.
- `reconcile_daily_trends.py` is deployment-safe recovery for legacy projects:
  it only syncs a configured GA4 or GSC source with zero daily rows, records
  failures in its summary, and never blocks the rest of the deployment batch.
