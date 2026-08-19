# Legacy script entry points

The scripts in this directory are retained for backwards compatibility only:

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
