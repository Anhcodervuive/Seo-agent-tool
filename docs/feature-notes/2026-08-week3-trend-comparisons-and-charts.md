# Week 3: Comparable Trends and Interactive Charts

**Status:** Delivered and verified locally on 20 August 2026

This note completes the analytical part of the Week 3 Trends dashboard. It
replaces the old first-point-to-last-point card calculation with comparable
periods and adds a detailed chart without slowing the initial project page.

## What users see

Open **Project → Trends**, choose **30**, **60**, or **90 days**, then click a
metric card to inspect its chart.

- Each card shows the current period value and its comparable-period change.
  The 30-day view is labelled **MoM**; 60/90-day views are correctly labelled
  **Period change**, rather than falsely calling them MoM.
- A separate **YoY** indicator appears when matching stored history exists.
- The large chart uses the actual observation date on its x-axis, tooltips,
  and an expandable table of the stored observations.
- If chart JavaScript is unavailable, the summary cards and observation table
  still work, with a lightweight SVG fallback.

## Calculation rules

| Metric | Current value | Comparable period | YoY |
| --- | --- | --- | --- |
| GA4 Sessions | Sum of daily sessions | Preceding equal-length daily window | Same calendar window last year |
| GSC Clicks | Sum of daily clicks | Preceding equal-length daily window | Same calendar window last year |
| GSC CTR | `total clicks / total impressions` | Same weighted calculation | Same weighted calculation |
| Crawl Issues | Latest completed crawl observation in the window | Latest observation in preceding window | Latest observation in matching window last year |
| Backlinks / Referring domains | Latest completed audit observation in the window | Same snapshot-observation rule | Same snapshot-observation rule |

For Google daily data, both compared windows need at least **70% date
coverage**. Otherwise the card keeps any current stored value but says that a
comparison is unavailable; it never manufactures a percentage from sparse
data. GSC uses its latest stored date as the comparison anchor because Search
Console can publish a few days late.

Crawl and backlink values are state observations, not daily totals. A chart
therefore only shows dates on which a completed audit recorded that metric.
Two audits on one day are reduced to the latest observation for that day.

## Data flow

```text
Stored GA4/GSC daily rows + completed audit observations
  -> bounded, indexed comparison query
  -> current / previous equal-period / same-period-last-year payload
  -> lazy Trends tab request
  -> selected metric canvas chart + accessible stored-observation table
```

The endpoint remains read-only. Opening Trends does not call Google,
DataForSEO, LibreCrawl, or the AI provider.

## Performance and cache policy

- The project page does not request Trend data or load Chart.js until the
  user opens the Trends tab.
- Chart.js is loaded once on demand. Data points are already sorted and passed
  in parsed `{x, y}` form; animations are short/respect reduced motion.
- The API reads one bounded range backed by the existing
  `(client_id, metric_date)` daily-metric index.
- Browser memory cache is per selected period and expires after 60 seconds.
  It is invalidated when the page reports a finished audit and is refreshed
  after the browser regains focus if stale.
- The chart preserves real date spacing. Snapshot observations are not
  stretched to look like evenly spaced daily values.

## Historical backfill for YoY

New projects will gradually retain daily rows because routine audits upsert a
rolling trend range without deleting older stored rows. A project that needs
YoY immediately can backfill one project deliberately:

```powershell
docker compose exec -T web python -m scripts.backfill_daily_trends --client-id 2 --dry-run
docker compose exec -T web python -m scripts.backfill_daily_trends --client-id 2 --days 455
```

`455` days is enough for the longest supported view: a current 90-day period
and its matching 90-day period one year earlier. The command only requests
GA4/GSC daily data for the named project and stores it locally; it does not run
a crawl, generate a report, or contact the AI provider. Use `--ga4-only` or
`--gsc-only` when appropriate.

Whether a provider returns the entire historical request still depends on that
project's configured provider access and retention. The UI will honestly keep
YoY unavailable until it has enough stored dates.

## Deployment and verification

No Alembic migration is required for this upgrade. The daily metric tables and
their composite `(client_id, metric_date)` indexes already exist.

```powershell
docker compose build web worker
docker compose up -d --force-recreate web worker
docker compose ps
python -m pytest tests/test_trend_analysis.py -q
```

Automated checks cover equal-window totals, weighted CTR, YoY, sparse daily
coverage, delayed GSC anchors, audit-observation comparisons, the rendered
route contract, the backfill date ranges, and JavaScript syntax.

## Remaining operational limit

Daily provider refresh still occurs as part of a successful audit. A standalone
scheduled daily refresh is intentionally deferred to the cost-control work in
Week 4.
