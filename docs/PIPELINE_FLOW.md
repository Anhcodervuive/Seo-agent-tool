# Audit Pipeline Flow

`Run Analysis` creates a snapshot and queues an audit job. The worker then
executes the selected stages. Each stage reports its own result, so an
optional provider failure can produce a `partial` snapshot while preserving
successful data.

The crawl stage is:

```text
LibreCrawl response
  -> services/crawl_data.py
     - normalize URLs
     - remove fragments and duplicate rows
     - reject rows without required values
     - record quality counters
  -> persist rows for the snapshot
```

The normalized crawl quality counters are stored under `snapshot.notes` as
`crawl_quality`. They are diagnostic metadata; existing crawl records and
report behavior remain compatible with the previous schema.

## Trend data

Rankings, crawl issues, and backlinks are audit observations and remain tied
to snapshots. GA4 and GSC trend charts use separate daily aggregates instead:

```text
GA4 / GSC API date report
  -> rolling 90-day upsert by client + calendar day
  -> ga4_daily_metrics / gsc_daily_metrics
  -> on-demand 30/60/90-day dashboard query
```

The dashboard never calls Google APIs. A completed audit refreshes the rolling
window, so a newly connected project receives up to 90 days of history on its
next successful full audit.

Snapshot statuses are `pending`, `running`, `complete`, `partial`, and
`failed`. Stage statuses are tracked separately in the run notes.
