# SEO Agent — Handover Guide

An automated system that audits client websites, analyses the data with AI, and produces
strategic reports with month-over-month trends. Runs on this VPS.

## What it does
For each client it pulls four data sources into a database, then an AI model analyses a
summary and generates a prioritised report:
1. Technical crawl (LibreCrawl) — on-site issues
2. GA4 — traffic by channel
3. Google Search Console — queries, clicks, impressions, position
4. DataForSEO — keyword search volume

## The interface
Open http://194.110.87.126:8080 in a browser.
- Home page: list of all projects (clients)
- "+ Add Project": add a new client (name, domain, GA4 property ID, GSC site URL, location, business context)
- Click a project: see its month-over-month trend, chat with its data, and read the latest report

## Adding a new client
1. Grant the service account read access to the client's GA4 and GSC:
   seo-agent-reader@seo-agent-client.iam.gserviceaccount.com
   - GA4: Admin → Property Access Management → add as Viewer
   - GSC: Settings → Users and permissions → add
2. In the interface, click "+ Add Project" and fill in the details.
3. That's it — the client is included in the next scheduled run.

## When audits run
Automatically every Monday at 06:00 (server time), for all active clients, one at a time.
To change the schedule: edit the cron job with `crontab -e`.
To run manually right now: `cd /opt/seo-agent/pipeline && ./run_scheduled.sh`

## Where things live
- Pipeline code + database: /opt/seo-agent/pipeline/
- Reports (markdown): /opt/seo-agent/pipeline/reports/
- Service account key: /opt/seo-agent/credentials/
- Scheduled-run log: /opt/seo-agent/pipeline/scheduled.log

## API keys (to swap in your own)
Keys are set in two places — update both if you change them:
1. /opt/seo-agent/pipeline/run_scheduled.sh (used by the scheduled run)
2. ~/.bashrc (used when running manually)
Keys used: OpenRouter (LLM), DataForSEO (login + password). The DataForSEO key is currently
a trial — replace it with your own paid key in both files above.

## The AI model
Currently GLM 5.2 via OpenRouter (set as OPENROUTER_MODEL). To change the model, update that
variable in run_scheduled.sh and ~/.bashrc.

## Services (kept alive automatically)
Managed by PM2 (survive reboots):
- librecrawl-technical-seo-audit-mcp — the crawler
- seo-interface — the web interface
Check status: `pm2 status`   Restart: `pm2 restart seo-interface`
