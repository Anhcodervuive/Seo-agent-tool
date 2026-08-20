# Week 3 Foundation: Keyword Movement, Trends, Health, and Fast Project Loading

**Status:** Foundation delivered on 19 August 2026; comparisons/chart upgrade delivered on 20 August 2026
**Primary commits:** `cc14509`, `24d154f`

This note covers the completed data and dashboard foundation for Week 3. The
AI Copilot chat/tool-calling layer is a later feature and is not included here.
For the current MoM/YoY semantics, interactive chart design, and historical
backfill command, see [Comparable Trends and Interactive Charts](2026-08-week3-trend-comparisons-and-charts.md).

## What users can do

### Keyword Movement

Open **Project → Keywords** to view tracked-keyword rankings without loading
the ranking dataset when the project first opens.

- Filter winners, losers, Page 1, Page 2, and all keywords.
- Search a keyword and choose device.
- See latest position, previous position, movement, and a small history trend.
- Export the visible project ranking dataset as CSV.

### 30/60/90-day Project Trends

Open **Project → Trends**, then choose 30, 60, or 90 days.

- GA4 sessions, GSC clicks, and GSC CTR use calendar-day data.
- Crawl issues, backlinks, and referring domains use completed-audit
  observations. They only change when an audit has captured those data types.
- The dashboard reads stored data only; opening the tab never calls Google.
- Cards compare equal time periods and show YoY only when the corresponding
  stored history exists; click a card to inspect the real-date chart.

### Project Health Score

The original overview score has been superseded by persisted Health Score v2.
See [Health Score v2 and AI Copilot](2026-08-week3-health-and-copilot.md) for
the current four-pillar formula, confidence rules, and operational details.

### Faster Project Dashboard

The initial project page now renders the shell and active-audit progress first.
Health, technical issues, keyword rankings, and audit history load separately
only when needed. This prevents a project with a large history from blocking
the first page render.

## Data flow and source of truth

```text
Successful audit worker
  -> GA4 date report / GSC date report
  -> rolling daily upsert by project + date
  -> ga4_daily_metrics / gsc_daily_metrics
  -> /project/<id>/trends/data?days=30|60|90
  -> Trends dashboard

Successful audit worker
  -> crawl, backlink, ranking records attached to a snapshot
  -> completed snapshot observations
  -> Trends / Keywords / Health / Audit History
```

Daily Google data is deliberately separate from snapshot report rows. A
snapshot's normal GA4/GSC report often covers an overlapping date range, so
summing snapshot reports would double-count traffic and search metrics.

### Why backlinks are stored by snapshot

Backlink totals and referring-domain counts are a point-in-time observation
returned by DataForSEO when an audit runs. They are stored in
`backlink_history` against that audit's snapshot so the application can answer
both of these questions accurately:

- What did the backlink profile look like when this report was generated?
- How did the profile change between completed audits?

The dashboard must not request live backlink data on every page load. Doing so
would spend API credits, add provider latency/rate-limit risk, and overwrite
the user's historical context with today's value. A live value cannot recreate
what the profile was 30 or 60 days ago unless it was recorded then.

For this reason backlink charts contain one observation per completed audit,
not one observation per calendar day. A future cost-controlled enhancement can
add a weekly backlink-only refresh job; it should still save each result as a
historical observation rather than fetch live during dashboard rendering.

## How daily Google history is refreshed

Each future successful audit asks GA4 and GSC for a rolling 90-day daily
window, then upserts those records. The latest successful sync wins for each
project/date and records which snapshot supplied it.

GSC deliberately ends three days before today because Search Console data is
commonly delayed. Its card and chart both use the latest complete stored
30/60/90-day range, so the chart ends at the GSC anchor date rather than
showing an incomplete tail through today.

For an existing project that was audited before this feature was deployed,
the daily tables may be empty. Backfill once with the configured Google
credentials, or run a new successful audit. The August 2026 local backfill
for Project #2 confirmed 90 GA4 and 90 GSC daily rows were stored.

## Metric calculation semantics

The dashboard has two different concepts: a **data point** in a chart and the
**summary change** shown on a card.

| Metric | One chart point | Stored source |
| --- | --- | --- |
| GA4 Sessions | Sessions for one calendar day | `ga4_daily_metrics` |
| GSC Clicks | Clicks for one calendar day | `gsc_daily_metrics` |
| GSC CTR | `(daily clicks / daily impressions) × 100` | `gsc_daily_metrics` |
| Crawl Issues | Total `CrawlIssue` rows in one crawled snapshot | Snapshot-owned crawl rows |
| Backlinks | Total backlinks returned by DataForSEO during one audit | `backlink_history` |
| Referring Domains | Total referring domains returned during one audit | `backlink_history` |

### Current comparison semantics

Daily GA4/GSC metrics now compare **equal calendar windows**. GA4 sessions and
GSC clicks are sums; GSC CTR is recomputed as total clicks divided by total
impressions. The 30-day view is MoM, while 60/90-day views use the more honest
label **Period change**. YoY uses the corresponding calendar range last year.

Crawl and backlink values remain point-in-time observations: the comparison is
between the latest completed audit in each relevant window. More crawl issues
are unhealthy, so an upward movement is red; more backlinks/referring domains
are normally green. Sparse daily data and unavailable historical comparisons
are explicitly labelled instead of producing a misleading percentage.

## Performance design

| Area | Behaviour |
| --- | --- |
| Audit history | Cursor pagination, 10 snapshots at a time. |
| Snapshot history index | PostgreSQL index: `(client_id, created_at, id)`. |
| Keywords | Fetches only after the Keywords tab opens; server pagination stays at 25 rows. |
| Website issues | Loads when the card approaches the viewport with `IntersectionObserver`. |
| Health | Fetches after the Overview shell renders; ranking statistics use SQL aggregates instead of loading all ranking rows. |
| Trends | Trend data and Chart.js load only after the Trends tab opens; the in-page period cache expires after 60 seconds and is invalidated after an audit finishes. |
| Requests | Browser uses `cache: 'no-store'` so newly completed or deleted snapshots are not hidden by stale browser responses. |

### Why audit metrics can match at 30, 60, and 90 days

Crawl and backlink values exist only for completed audits. If every completed
audit is less than 30 days old, all three selectors contain the same audit
points. That is accurate: the 60/90-day windows have no earlier observations
to add. In contrast, Google daily series should have different point counts as
soon as the daily tables contain history.

## Deployment and migration checklist

The snapshot-history index migration is:

```text
pipeline/migrations/versions/i6d7e8f9a0b1_add_snapshot_history_index.py
```

Apply migrations from `pipeline/`:

```powershell
python -m flask --app manage.py db upgrade
```

When running with Docker, rebuild/recreate **both** `web` and `worker` after
pulling an application change that adds a migration or worker logic:

```powershell
docker compose build web worker
docker compose up -d --force-recreate web worker
docker compose ps
```

An old container image cannot recognize a newly applied Alembic revision and
will restart while trying to migrate. It also cannot execute newly added daily
sync code even if the source on the host is current.

## Verification checklist

1. Run `python -m unittest discover -s tests -p "test_*.py"` from `pipeline/`.
2. Confirm `python -m flask --app manage.py db current` reports the current
   Alembic head for the deployed image.
3. Confirm both `web` and `worker` are running; worker must become `healthy`.
4. Open Trends and verify 30/60/90 changes the current-period cards, the
   comparable-period labels, and the real-date detail chart.
5. If GA4/GSC are blank, check the row counts in `ga4_daily_metrics` and
   `gsc_daily_metrics`, then inspect `docker compose logs worker` for
   `daily trend sync unavailable`.
6. Open Keywords and Audit History to confirm they load on first tab visit,
   pagination works, and snapshot deletion remains available.

## Known limits

- YoY stays unavailable until the matching stored history exists. Use the
  documented one-project backfill when an existing project needs it now.
- Crawl/backlink trends cannot show days without a completed audit.
- The daily Google refresh currently occurs as part of a successful audit;
  a standalone scheduled daily refresh is a future cost/automation feature.
