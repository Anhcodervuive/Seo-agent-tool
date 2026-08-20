# Deployment Daily Trend Reconciliation

**Status:** Delivered on 20 August 2026

## Purpose

The Trends dashboard reads daily GA4 and Google Search Console (GSC) data from
the application's database. Projects audited before daily trend storage existed
can have audit snapshots but no daily rows, leaving GA4 Sessions, GSC Clicks,
and GSC CTR empty.

Staging deployment now runs this recovery command after migrations and service
restart:

```bash
python -m scripts.reconcile_daily_trends --only-missing --days 455
```

## Behavior

For every project, the command checks GA4 and GSC independently.

- A source is eligible only when it is configured and has **zero** daily metric
  rows.
- Each eligible source receives up to 455 days of provider history.
- A source with one or more stored daily rows is skipped, with no provider API
  request.
- A GA4 failure does not prevent GSC for the same project; one failed project
  also does not stop other projects.
- Failures are included in the deployment log summary, but the command exits
  successfully so a temporary provider issue cannot block deployment.

This is intentionally a **zero-history recovery**, not a periodic refresh.
Existing and partially populated daily series remain the normal audit flow's
responsibility. That prevents expensive full-history Google API calls on every
deployment.

## Operations

Preview candidates without making provider calls:

```bash
docker compose exec web python -m scripts.reconcile_daily_trends --dry-run
```

Limit a manual recovery run:

```bash
docker compose exec web python -m scripts.reconcile_daily_trends --max-projects 5
```

`--max-projects 0` is the default and processes every eligible project. The
command logs one result per project/source plus a final JSON summary.

## Relationship to snapshots

Snapshots remain the historical report boundary. Their GA4/GSC counters are
cache-row counts, not daily metric series, so they cannot populate a trend
chart by themselves. Reconciliation fetches the daily data required by Trends;
it does not modify or reinterpret any snapshot.

## Verification

1. Run `python -m scripts.reconcile_daily_trends --dry-run` in the `web`
   container and inspect selected project/source entries.
2. Deploy staging and inspect the `[daily-trend-reconcile]` log lines.
3. Confirm an eligible project's `ga4_daily_metrics` or `gsc_daily_metrics`
   row count becomes positive, then refresh its Trends tab.
4. Confirm a project with existing daily rows is logged as absent from the
   selected batch and receives no new backfill request.
