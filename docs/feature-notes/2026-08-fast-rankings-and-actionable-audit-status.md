# Faster Ranking Collection and Actionable Audit Status

**Delivered:** 25 August 2026

**Scope:** full-audit latency, DataForSEO result collection, and Audit History
status explanations.

## What changed for users

A snapshot no longer presents only a vague `partial` or `failed` label. Audit
History and Snapshot Details now show:

1. A plain-language outcome: **Completed**, **Completed with warnings**,
   **Needs attention**, **In progress**, or **Queued**.
2. The exact affected data source.
3. What data remains valid.
4. The recommended next action.
5. A collapsible, safe technical diagnostic for support and developers.

For example, an AI report HTTP 404 now reads as “The AI report was not
generated; all available audit data was saved,” while a DataForSEO outage says
how many checks could not be verified and explicitly confirms that valid
ranking/not-in-Top-100 results remain usable.

## Faster ranking flow

```text
Start full audit
    ├─ submit Standard SERP tasks immediately (up to 100 per API request)
    └─ run crawl, GA4, GSC, backlinks, and competitor data
                ↓  provider processes the queued SERP tasks in parallel
Ranking stage
    └─ collect ready task results with a bounded concurrent worker pool
```

Previously, the audit waited to submit rankings until after the earlier data
stages, and then downloaded each ready SERP task result one at a time. The new
flow overlaps provider-side ranking work with the independent audit stages and
retrieves ready results concurrently (12 workers by default).

The concurrency limit is intentionally below DataForSEO's published API limit.
It improves application-side retrieval time without turning an audit into an
unbounded request burst. DataForSEO still controls how quickly Google SERP
tasks themselves complete.

## Live progress that reflects parallel work

The live analysis card now shows three separate facts instead of pretending
that keyword ranking is a sequential step:

1. **Overall workflow:** the current audit stage, number of finished stages,
   and a bounded progress bar. The bar only uses a partial fraction when the
   crawler reports discovered URLs or when ranking results are actively being
   collected; it never invents provider completion percentages.
2. **Website crawl:** crawled, pending, and discovered URL counts from
   LibreCrawl.
3. **Keyword rankings:** explicit DataForSEO state such as *Preparing*,
   *Processing in DataForSEO (background)*, *Collecting results*, *Collected
   with issues*, or *Timed out*. During the parallel part of a full audit, the
   card states how many checks were submitted to DataForSEO instead of showing
   a misleading `0/N complete` count.

This state is supplied by the analysis-progress API as a presentation object.
The raw counters remain in `Snapshot.notes.progress`, so active snapshots
created by older deployments still receive a safe fallback display. No
database migration is required.

## Configuration and cost policy

All settings are optional and documented in
[`pipeline/.env.example`](../../pipeline/.env.example).

```dotenv
DATAFORSEO_RANKING_POLL_SECONDS=5
DATAFORSEO_RANKING_MAX_WAIT_SECONDS=900
DATAFORSEO_RANKING_RESULT_WORKERS=12
DATAFORSEO_RANKING_PRIORITY=normal
```

`normal` is the default because it preserves the existing cost expectation.
DataForSEO also supports `high` task priority. Set
`DATAFORSEO_RANKING_PRIORITY=high` only after the account owner accepts its
higher provider pricing; it is the supported option when provider queue time,
not application retrieval, is the remaining bottleneck.

No database migration is required. The temporary task state remains in
`Snapshot.notes` only while the ranking stage is active. Existing snapshots
receive the clearer history explanation from their stored notes where possible.

## Operational verification

1. Deploy/restart both `web` and `worker` containers.
2. Run a full audit with a non-critical project that has tracked keywords.
3. Confirm worker logs show `ranking.submission_prepared` near the beginning
   of the audit, before crawl completion.
4. Confirm `ranking.result_collection_started` logs a bounded worker count and
   `ranking.stage_finished` records correct found/not-found/unavailable counts.
5. Open Audit History and verify that a partial audit names the failed source,
   retained data, next action, and technical detail.
6. While the same audit is running, confirm the live card shows both the
   active workflow stage and `Processing in DataForSEO (background)` before
   the ranking collection stage begins.
7. If fast provider delivery is approved, set the `high` priority environment
   value and rerun the same scope. Compare stage durations and DataForSEO cost
   before using it for all scheduled audits.

## Known limits

- A full audit can still take time to crawl a large site. Ranking submission
  now overlaps that work but does not remove crawl time.
- Normal-priority Standard SERP tasks can wait in DataForSEO's provider queue.
  The application cannot force Google/DataForSEO to finish sooner; use the
  documented high-priority setting only when its cost trade-off is acceptable.
- Result retrieval is concurrent, but database writes stay in the main worker
  transaction to avoid unsafe cross-thread SQLAlchemy sessions.

## Verification included

Automated tests cover concurrent bounded result retrieval, reuse of
background-submitted tasks without resubmission, old/new audit status
explanations, and the existing ranking status regressions.

## Commit

`Improve ranking latency and audit diagnostics`
