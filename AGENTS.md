# AGENTS.md

## Project Purpose

SEO Copilot is an internal web application for SEO teams. It stores project configuration, runs repeatable SEO audits, collects search/traffic data, and presents the underlying data used to produce AI-assisted SEO reports.

## Architecture

- `pipeline/` is the Flask application and orchestration layer.
- LibreCrawl is a separate crawler service. The pipeline calls its HTTP API and stores normalized/raw crawl data in PostgreSQL.
- PostgreSQL is the source of truth for projects, snapshots, collected metrics, crawl findings, and configuration.
- The UI is server-rendered with Jinja templates and CSS/JavaScript served by Flask.
- Docker runs the app with Gunicorn; the container entrypoint applies migrations before starting the web server.

## Repository Layout

- `pipeline/app/`: Flask app factory, models, routes, templates, and static assets.
- `pipeline/services/`: LibreCrawl, GA4, GSC, DataForSEO, analysis, and PDF integration logic.
- `pipeline/migrations/`: Flask-Migrate/Alembic environment and revisions.
- `pipeline/secure/` and repository-level `credentials/`: local/deployment-only credential material; never commit secrets.
- `pipeline/reports/` and generated report assets: Markdown/PDF report artifacts.
- `pipeline/docker-compose.yml`: application, PostgreSQL, and pgweb services.
- `librecrawl/`: the separate LibreCrawl service and Compose configuration.
- `docs/`: project notes and feature status documentation.

## Tech Stack

- Python 3.11 in Docker
- Flask, Flask-Login, SQLAlchemy, Flask-Migrate/Alembic
- PostgreSQL 15 and Gunicorn
- Jinja2, HTML/CSS/JavaScript
- Google Analytics Data API and Google Search Console API
- DataForSEO SERP/backlink APIs
- LibreCrawl HTTP API
- WeasyPrint for PDF downloads; Docker provides its native libraries.

## Database

The default Compose database is PostgreSQL service `seo_agent_db`, database `seo_agent`, user `seo_user`, with host port `5434` mapped to container port `5432`. Preserve the persistent Compose volume during rebuilds.

Important data areas include clients/projects, snapshots, tracked keywords, rankings, GA4 metrics, GSC metrics, backlinks, competitors, crawl issues, raw crawl pages/links/images/structured data, Google account configs, and AI settings.

Use migrations as the schema contract. Do not casually edit production tables or use `db stamp` to hide a mismatch. A stamp records a revision; it does not apply missing schema changes.

## Run Locally

From the repository root:

```powershell
cd pipeline
docker compose up -d --build
docker compose ps
docker compose logs -f seo_agent_web
```

Use `docker compose up -d --build` after code, Dockerfile, dependency, or image changes. For runtime `.env`/Compose changes where the image is unchanged, recreate the app when needed:

```powershell
docker compose up -d --force-recreate
```

The app is normally exposed on port `8080`; pgweb is normally exposed on `8081`. Exact mappings are defined in `pipeline/docker-compose.yml`.

Running `python run.py` directly from `pipeline` is possible, but local PDF export requires WeasyPrint's native GTK/Pango libraries on Windows. Prefer Docker for end-to-end PDF testing.

## Migrations

Run from `pipeline` or inside the app container in deployment:

```bash
python -m flask --app manage.py db current
python -m flask --app manage.py db history
python -m flask --app manage.py db migrate -m "describe schema change"
python -m flask --app manage.py db upgrade
```

Deployment flow: back up the database and secure/runtime files, pull the code, rebuild/recreate the app if required, run `db upgrade`, then inspect app logs and smoke-test the UI. Keep database volumes and secure mounts intact.

## Testing

- Check migration state with `db current` and confirm the expected revision is the head with `db history`.
- Run `python -m compileall -q app services run.py manage.py` for a fast syntax check.
- Run `docker compose logs -f seo_agent_web` while triggering an analysis.
- Smoke-test login, project creation/editing, analysis, snapshot data/report/PDF downloads, CSV exports, issue category expansion, and theme switching.
- Verify the selected snapshot contains expected crawl, GA4, GSC, and ranking row counts before judging UI output.

There is no assumption of a complete automated test suite; add focused tests when changing pipeline parsing, migrations, or destructive operations.

## Configuration and Secrets

Runtime configuration is supplied through `pipeline/.env` or deployment environment variables. Important variables include the database URL, `SECRET_KEY`, LibreCrawl URL/timeouts, Google/DataForSEO credentials, AI settings, and admin bootstrap credentials.

Container networking matters: `127.0.0.1` inside the pipeline container means the pipeline container itself. When LibreCrawl is separate, use a shared Docker network/service name or the configured host gateway such as `host.docker.internal`. Do not expose LibreCrawl publicly without authentication/firewall controls.

Google service-account JSON and DataForSEO credentials are sensitive. Use managed upload/storage or deployment secrets, keep credential directories out of Git, and never place keys in reports, logs, screenshots, or this file.

GA4 requires a numeric property ID and a service account granted access to that property. GSC requires the exact property identifier (`sc-domain:example.com` or the matching URL property) and access for the selected service account. DataForSEO rank data may be unavailable because of billing, IP allowlisting, fraud/rate limits, or invalid keywords; represent that as partial data rather than a schema failure.

## Conventions and Guardrails

- Preserve the Flask/Jinja architecture and service boundaries; keep integration logic out of templates/routes where possible.
- Store each analysis run as a snapshot and keep source counts/errors so users can see what data was used.
- Prefer additive Alembic migrations over manual production schema edits.
- Preserve existing data volumes and take a backup before destructive migrations, snapshot deletion, or Compose volume operations.
- Keep external API failures isolated per module so a failed ranking/GA4/GSC call does not discard successful crawl data.
- Treat nullable ranking URL/position and missing third-party fields as valid partial-data cases.
- Keep UI tables bounded/scrollable or tabbed for large datasets; do not render unbounded raw error text into narrow cards.

## Current Status

Implemented foundations include authentication, project/client management, per-project Google account and AI overrides, snapshots, crawl/GA4/GSC collection, keyword metadata and bulk entry, ranking history/movement display, crawl issue grouping, raw LibreCrawl tables, content/media reports, CSV/PDF exports, date/dimension filtering, column sorting, health scores, and light/dark/device theme selection.

The AI agentic tool-calling layer and complete competitor intelligence workflow remain future/partial work. Full sitemap, page-speed, advanced structured-data validation, redirect-chain/loop analysis, and some competitor/backlink capabilities depend on crawler/API fields being available and should not be claimed as complete without verifying current source data.
