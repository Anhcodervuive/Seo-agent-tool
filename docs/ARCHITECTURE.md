# SEO Copilot Architecture

## Runtime flow

```text
Browser
  -> Flask route
  -> service layer / audit queue
  -> worker pipeline stages
       -> LibreCrawl
       -> GA4 / GSC / DataForSEO
       -> report generator
  -> PostgreSQL snapshot
  -> dashboard, AI tools, and exports
```

Flask routes are responsible for authentication, request parsing, and HTTP
responses. Domain operations belong in `pipeline/services/` so they can be
used by web requests, workers, CLI scripts, and future MCP tools.

## Main boundaries

- `pipeline/app/routes/`: HTTP and access-control concerns.
- `pipeline/services/`: integrations, pipeline orchestration, persistence
  helpers, reporting, and domain calculations.
- `pipeline/app/models.py`: database schema and relationships.
- `pipeline/tests/`: unit and contract tests that do not require live APIs.

Snapshot child rows use PostgreSQL `ON DELETE CASCADE`. The migration for
those constraints must be applied before relying on database-owned cleanup.

For trend performance, GA4 and GSC daily totals are stored independently from
snapshot reports and indexed by project/date. This prevents overlapping
28-day snapshot ranges from being interpreted as daily traffic trends.
