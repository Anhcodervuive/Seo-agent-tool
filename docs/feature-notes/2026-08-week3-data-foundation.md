# Week 3 Foundation: Keyword Movement, Trends, Health, and Fast Project Loading

**Status:** Delivered and verified locally on 19 August 2026
**Primary commits:** `cc14509`, `24d154f`

This note covers the completed data and dashboard foundation for Week 3. The
AI Copilot chat/tool-calling layer is a later feature and is not included here.

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
commonly delayed. A 90-day selector may therefore have 87 visible GSC points,
which is expected rather than a missing-data error.

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

For every selected window, the current summary logic uses the first and last
available point in that window:

```text
latest   = final available point
previous = first available point
change   = latest - previous
percent  = (change / previous) × 100
```

For example, crawl issues moving from 1,491 to 1,869 produces `+378` and
`+25.4%`. More crawl issues are unhealthy, so the UI treats an upward movement
as red. More backlinks/referring domains are normally healthy, so their upward
movement is green.

### Important current limitation

This is a first-to-last-point baseline, not a true Month-over-Month or
Year-over-Year calculation. A GA4 change of `-60%` currently means the final
day had 60% fewer sessions than the first available day; it does **not** mean
the whole 30-day traffic total declined by 60%.

The next level of trend analysis should calculate equal-window comparisons:

```text
Current 30-day total  = sum of selected 30 days
Previous 30-day total = sum of the preceding 30 days
MoM                    = (current - previous) / previous

Current CTR            = current-window total clicks / total impressions
Previous CTR           = previous-window total clicks / total impressions
```

That method is more stable than comparing two individual days and is the
appropriate path for the Week 3 MoM/YoY requirement. Crawl and backlink data
will still compare audit observations until a separate scheduled collection
job is introduced.

## Performance design

| Area | Behaviour |
| --- | --- |
| Audit history | Cursor pagination, 10 snapshots at a time. |
| Snapshot history index | PostgreSQL index: `(client_id, created_at, id)`. |
| Keywords | Fetches only after the Keywords tab opens; server pagination stays at 25 rows. |
| Website issues | Loads when the card approaches the viewport with `IntersectionObserver`. |
| Health | Fetches after the Overview shell renders; ranking statistics use SQL aggregates instead of loading all ranking rows. |
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
2. Confirm `python -m flask --app manage.py db current` reports
   `i6d7e8f9a0b1 (head)`.
3. Confirm both `web` and `worker` are running; worker must become `healthy`.
4. Open Trends and verify 30/60/90 changes the line/card summaries and point
   count for GA4/GSC when daily history exists.
5. If GA4/GSC are blank, check the row counts in `ga4_daily_metrics` and
   `gsc_daily_metrics`, then inspect `docker compose logs worker` for
   `daily trend sync unavailable`.
6. Open Keywords and Audit History to confirm they load on first tab visit,
   pagination works, and snapshot deletion remains available.

## Known limits

- The trend summaries compare the first and final available point in the
  selected window; they are not yet MoM/YoY calculations.
- Crawl/backlink trends cannot show days without a completed audit.
- The daily Google refresh currently occurs as part of a successful audit;
  a standalone scheduled daily refresh is a future cost/automation feature.
