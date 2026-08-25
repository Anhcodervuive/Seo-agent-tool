# Deferred DataForSEO Ranking Reconciliation

**Delivered:** 25 August 2026

**Scope:** reduce user-facing audit latency when DataForSEO Standard SERP tasks
remain in the provider queue, while preserving every already-submitted task.

## Why this changed

One project with 100 tracked keywords and one competitor creates 200 ranking
checks: 100 for the project domain and 100 for the competitor domain. DataForSEO
accepts those tasks quickly, but normal-priority Standard tasks can become ready
at different times.

The earlier flow held the full audit open for the entire provider timeout
(15 minutes by default). Any task not ready at that point was stored as a
failed check. This made a healthy crawl/GA4/GSC audit feel slow and could turn
a provider queue delay into a permanent-looking ranking failure.

## New flow

```text
Full audit starts
    ├─ Submit all Standard SERP tasks once
    ├─ Run crawl, GA4, GSC, backlinks, and competitor stages in parallel
    └─ Collect ready ranking results during a short foreground window
                    ↓
        Still-processing provider tasks?
                    ↓ yes
Snapshot is saved as "Completed with warnings"
    ├─ Existing ranking results remain visible
    ├─ UI says the remaining checks are still processing
    └─ Durable reconciliation job polls only when the audit worker is idle
                    ↓
All remaining tasks become ready / the full provider wait limit is reached
    └─ Snapshot, health score, Audit History, and live card are updated
```

The worker never sends duplicate DataForSEO tasks during reconciliation. It
uses the original task IDs stored with the snapshot, so the follow-up only
retrieves results that the provider has already processed.

## User-facing behaviour

During the short foreground wait, the normal live progress card remains the
same. If DataForSEO still has tasks in progress afterwards:

- The audit completes without waiting for the full provider timeout.
- The card remains visible after page refresh and says, for example,
  `148 of 200 results saved · 52 will sync automatically in the background.`
- Audit History explains that no action is needed and confirms that existing
  ranking and confirmed “Not in Top 100” results remain valid.
- The card keeps polling while reconciliation is active. It reloads normally
  after the final result is available or a genuine provider timeout occurs.

Only after the full provider wait limit expires are unresolved tasks marked as
`failed`. A provider timeout is therefore distinct from a keyword that is
correctly reported as `not_found`.

## Queue and data model

`ranking_reconciliation_jobs` is a one-per-snapshot, PostgreSQL-backed queue.
It records the next provider poll time, attempts, last worker error, and final
state. Its foreign keys cascade with the project/snapshot, so deleting a
snapshot also deletes its pending reconciliation work.

The existing `audit_jobs` queue always has priority. Copilot work also runs
before reconciliation. When the worker has no primary audit or Copilot task,
it claims at most one due ranking reconciliation job. PostgreSQL row locking
with `SKIP LOCKED` keeps this safe when multiple workers are introduced.

The actual DataForSEO task IDs and check context remain in
`Snapshot.notes.ranking_task_state` until reconciliation ends. This prevents a
second submission after worker restarts. The durable queue row makes finding
the next due snapshot efficient without scanning all snapshot notes.

## Configuration

All values are optional; the defaults are in
[`pipeline/.env.example`](../../pipeline/.env.example).

```dotenv
# Poll rapidly only while the user is waiting.
DATAFORSEO_RANKING_POLL_SECONDS=5
DATAFORSEO_RANKING_FOREGROUND_WAIT_SECONDS=300

# Preserve the former overall provider wait budget.
DATAFORSEO_RANKING_MAX_WAIT_SECONDS=900

# Poll deferred provider tasks once per minute when the worker is idle.
DATAFORSEO_RANKING_RECONCILIATION_POLL_SECONDS=60
DATAFORSEO_RANKING_RESULT_WORKERS=12
DATAFORSEO_RANKING_PRIORITY=normal
```

With the defaults, the user-facing wait is at most five minutes from submission
(and usually less because submission overlaps crawl and other data collection).
The background worker can continue collecting the same tasks until the existing
15-minute provider limit. `normal` remains the cost-preserving default;
`high` priority is optional and must only be enabled after accepting the
DataForSEO price trade-off.

## Deployment and verification

This release includes a required database migration:

```bash
cd /opt/seo-agent-test/pipeline
docker compose up -d --build
```

Docker Compose runs a dedicated migration service before the web and worker
services start, so a freshly deployed worker cannot query a table before its
migration exists. The web startup check remains as a safe no-op verification.
Confirm the migration and worker health with:

```bash
docker exec seo_agent_db psql -U seo_user -d seo_agent -P pager=off -c "\d ranking_reconciliation_jobs"
docker compose ps
```

For a project with rankings, verify logs in this order:

1. `ranking.submission_finished` confirms tasks were accepted.
2. `ranking.reconciliation_scheduled` appears only when the short foreground
   wait ends with remaining provider tasks.
3. `ranking.reconciliation_started` and
   `ranking.reconciliation_deferred` show low-priority background collection.
4. `ranking.reconciliation_finished` has `resolution=complete` when all tasks
   arrive, or `resolution=timed_out` only after the complete provider budget.

## Regression coverage

Automated tests cover:

- deferring unready tasks without creating false `failed` rows;
- background result collection and snapshot completion;
- genuine timeout marking only after the full provider budget;
- persistence of stage diagnostics in `Snapshot.notes`;
- live-card rendering after a browser refresh; and
- the user-facing Audit History explanation for deferred tasks.
