# SEO Agent — Technical Documentation

## Overview
An automated SEO audit and analysis system. For each client it collects data from four
sources, stores dated snapshots, runs AI analysis, and serves results through a web interface.
Built in Python. Runs on the VPS, kept alive by PM2, scheduled via cron.

## Architecture / data flow
1. queue_run.py runs all active clients sequentially (scheduled weekly via cron).
2. For each client, run_client.py creates a snapshot and pulls four sources:
   - Technical crawl: LibreCrawl (self-hosted Docker container on port 5080)
   - GA4: Google Analytics Data API (service account)
   - Google Search Console: Search Console API (same service account)
   - DataForSEO: keyword search volume (google_ads/search_volume endpoint)
3. All data is written to a dated snapshot in the SQLite database (seo_agent.db).
4. analyze.py condenses the snapshot into a brief and sends it to an LLM (via OpenRouter)
   with a strategic SEO prompt, producing a markdown report.
5. trends.py compares the two most recent snapshots per client (traffic, search, technical,
   keyword movements).
6. app.py (Flask) serves the web interface reading from the same database.

## Files
- init_db.py         — creates the database schema
- run_snapshot.py    — per-source data pulls (crawl, GA4, GSC, rankings)
- run_client.py      — full run for one client (snapshot + analysis)
- queue_run.py       — sequential queue over all active clients + status
- analyze.py         — builds the brief, calls the LLM, saves the report
- trends.py          — month-over-month comparison logic
- dataforseo.py      — DataForSEO keyword enrichment
- app.py             — Flask web interface (projects, trends, chat, exports, model switcher)
- config.py          — API keys / model config (reads env vars)
- run_scheduled.sh   — cron wrapper (loads env, runs the queue)

## Database schema (SQLite: seo_agent.db)
- clients        — one row per client (name, domain, ga4_property_id, gsc_site_url, location, business_context)
- snapshots      — one row per audit run per client (dated, status)
- crawl_issues   — technical issues per snapshot
- ga4_metrics    — traffic per snapshot
- gsc_metrics    — search queries per snapshot
- rankings       — DataForSEO keyword search volume per snapshot
- settings       — key/value (currently: selected AI model)

## External services
- LibreCrawl: Docker container, localhost:5080 (MCP server on 5081)
- Google service account: seo-agent-reader@seo-agent-client.iam.gserviceaccount.com
  (needs Viewer on each client's GA4 property + GSC property)
- OpenRouter: LLM access (model configurable in UI / settings table)
- DataForSEO: currently a trial key (replace with production key in run_scheduled.sh and ~/.bashrc)

## Where Phase 2 would extend this
- Tracked keywords: new table + DataForSEO rank tracking over time + a history/chart screen
- Historical trends (30/60/90/365d): trends.py already compares snapshots; extend to aggregate
  over longer windows (data accumulates as scheduled runs build history)
- Agentic tool access: give the LLM live tool-calling to the four APIs rather than a pre-built brief
- Multi-account OAuth: extend the single service-account model to multiple accounts/properties
- Auth/multi-user: add a login layer in front of app.py
- Proactive monitoring: a scheduled job comparing latest metrics against thresholds, generating alerts

## Running it
- Interface: http://<server-ip>:8080 (served by PM2 process "seo-interface")
- Manual full run: cd /opt/seo-agent/pipeline && ./run_scheduled.sh
- Scheduled: weekly via cron (crontab -l to view)
- Service status: pm2 status
