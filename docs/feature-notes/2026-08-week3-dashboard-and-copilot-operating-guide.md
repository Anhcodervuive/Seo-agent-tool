# Week 3 Dashboard and AI Copilot: Operating Guide

**Status:** Delivered and documented on 20 August 2026
**Audience:** Developers, support engineers, project admins, and future Week 4 implementers.
**Client companion:** [Vietnamese client user guide](../user-guides/seo-copilot-client-guide-vi.md).

## Purpose and product contract

Week 3 delivers a usable project intelligence layer without turning normal page
loads or chat questions into uncontrolled provider/API calls. The product has
four completed pillars:

1. keyword movement dashboard;
2. comparable 30/60/90-day trend dashboard and charts;
3. versioned Project Health Score v2; and
4. read-only, tool-calling AI SEO Copilot.

The central contract is deliberately simple:

> **An audit collects and persists SEO observations. Dashboard and Copilot read
> those observations. Neither refreshes a provider nor mutates project data on
> a normal view/chat request.**

This avoids unexpected DataForSEO/Google/LibreCrawl costs, keeps the initial
project page responsive, and preserves a defensible historical record.

## Current runtime topology

```text
Browser
  -> Flask project dashboard
       -> PostgreSQL: read bounded/project-scoped records
       -> lazy tab APIs: trends, keywords, history, health, issues, chat state

Audit worker
  -> LibreCrawl REST service :5080
  -> Google / DataForSEO providers when the selected audit requires them
  -> PostgreSQL: Snapshot + daily metric/history rows + Health Score

Copilot worker path
  -> PostgreSQL: persisted conversation + bounded recent messages
  -> OpenRouter function-calling request
  -> internal, read-only project ToolRegistry
  -> PostgreSQL: tool result, assistant message, invocation audit trail

librecrawl/mcp-server :5081
  -> present in repository, but not started by pipeline/docker-compose
  -> not called by dashboard, audit worker, or current Copilot execution path
```

The phrase “tool-calling” in the Copilot release means that OpenRouter chooses
from server-provided function definitions. It does **not** mean that the model
can call arbitrary services, select another client/project, or initiate a live
crawl.

## Feature-to-source-of-truth map

| Feature | Primary stored source | Refresh/create event | Read behavior |
| --- | --- | --- | --- |
| Overview technical issues | Latest crawl-backed `Snapshot` + `CrawlIssue` | Full audit crawl | Lazy after overview shell approaches viewport |
| Keyword dashboard | Project `Ranking` rows/history | Full audit or ranking-only check | Load only when Keywords opens; paged server result |
| GA4/GSC trends | `ga4_daily_metrics`, `gsc_daily_metrics` | Successful audit rolling daily upsert / deliberate backfill | Load only when Trends opens |
| Crawl issue trend | Completed crawl `Snapshot` observations | Full audit crawl | One point per audit, not one point/day |
| Backlink trend | `backlink_history` joined to `Snapshot` | Audit-side DataForSEO collection | One point per audit, not one point/day |
| Health Score v2 | `health_scores` linked to a snapshot | Persisted after the normal audit stages | Overview lazy card; never recalculated in browser |
| Copilot answer | Existing project records listed below | User message queues a read-only run | Cursor-paged conversation state + delta polling |

Daily Google records are intentionally separate from snapshot report rows.
Snapshot reports commonly cover overlapping date ranges; aggregating them for a
trend would double-count traffic/search performance. Snapshot observations are
the correct temporal model for crawl and backlinks because those sources are
point-in-time audit outputs.

## Dashboard semantics and dependencies

### Keyword Movement

- Filters: all, winners, losers, Page 1, Page 2; search and device selection.
- Row fields: latest position, previous position, movement, compact history.
- Requires project-owned tracked keywords and at least one successful ranking
  check to populate ranking results.
- Competitor ranking rows must not be mixed into the project keyword summary.
- Export is a CSV of the visible project ranking dataset.

### Trends

The Trends endpoint accepts 30, 60, or 90 days and always reads stored data.
Its server-side comparison logic has these invariants:

| Metric | Current window | Prior comparison | Year-over-year |
| --- | --- | --- | --- |
| GA4 Sessions | Sum of daily sessions | Previous equal-length window | Same calendar window prior year |
| GSC Clicks | Sum of daily clicks | Previous equal-length window | Same calendar window prior year |
| GSC CTR | Weighted total clicks / impressions | Same weighted method | Same weighted method |
| Crawl Issues | Latest completed audit observation in window | Latest observation in previous window | Latest observation in matching last-year window |
| Backlinks/referring domains | Latest completed audit observation in window | Same snapshot-observation rule | Same snapshot-observation rule |

Rules that must not regress:

- Daily comparisons require at least 70% calendar-date coverage in both
  periods. When incomplete, retain the stored current value but label the
  comparison unavailable.
- GSC uses its latest stored date as the anchor because GSC reports can lag
  behind the current date.
- The 30-day label is MoM. The 60/90-day label is Period change, not MoM.
- Snapshot-derived points retain real observation dates; do not stretch them to
  equal visual daily spacing.
- Empty GA4/GSC on older projects is a data-history problem, not a browser
  rendering problem. Use a successful future audit or the deliberate
  `scripts.backfill_daily_trends` process.

### Health Score v2

Health Score is a persisted, versioned record rather than a client-side
calculation. The v2 nominal weights are Technical 35%, Organic 30%, Keywords
20%, and Backlinks 15%. It reweights only usable pillars and emits confidence
so missing GA4/GSC/ranking/backlink data is not misrepresented as zero.

The score's historical meaning is tied to the Snapshot that created it. A
future algorithm must use a new formula version; it must not overwrite existing
`v2` records.

### Snapshot behavior

A Snapshot is both the historic audit/report boundary and the source of
crawl/backlink observations. It continues to be valuable after Copilot exists:

- reports/crawl issues are time-specific;
- backlink totals are point-in-time observations;
- keyword history includes audit results; and
- Trends need those observations for technical/backlink history.

Deleting a snapshot cascades its attached raw crawl and related history data.
Support should treat it as a deliberate cleanup action, not as a way to refresh
the current dashboard.

## Copilot execution model

### Request lifecycle

```text
POST /project/<client_id>/copilot/messages
  -> authorize user/project
  -> persist CopilotConversation + user CopilotMessage
  -> persist CopilotRun(status=pending)
  -> return HTTP 202 to browser
  -> audit_worker claims the run using DB-safe locking
  -> run_copilot_run performs bounded provider/tool loop
  -> persist tool invocation audit trail + assistant message
  -> browser delta-polls current run and new messages
```

The user route never waits for the model response. While a conversation has a
pending/running run, it rejects another message so two agent runs cannot race
over the same context.

### Tool contract

`ToolContext(client_id, user_id, run_id)` is server-generated. It is not a
model argument and it is not exposed through schemas. The current standard
tools are:

| Tool | Project-scoped stored data |
| --- | --- |
| `get_ga4_data` | Daily sessions/users |
| `get_gsc_data` | Daily clicks/impressions/CTR/position |
| `get_rankings` | Tracked project keyword movement |
| `get_backlinks` | Project backlink/referring-domain history |
| `get_crawl_issues` | Groups from the latest completed crawl |
| `get_competitor_data` | Stored competitor insights |
| `get_project_health` | Latest persisted Health Score v2 |

Schemas reject unknown fields. Daily date ranges are bounded to 7–90 days,
lists to 100 rows, and the agent loop to 4 reasoning turns/6 tool calls. Tool
outputs are treated as data, not instructions. Each invocation is recorded in
`copilot_tool_invocations` with arguments, result status, duration, and error.

### Provider and history boundaries

- Provider: OpenRouter through the isolated `copilot_provider.py` adapter.
- Context: latest 12 user/assistant messages, not the entire conversation.
- Browser history: newest 30 messages on first load, older messages via
  `before_message_id`, new messages via `after_message_id`.
- Database: `ix_copilot_messages_conversation_id_id` supports cursor access.
- Cache: no global chat cache; authorization-sensitive, changing state uses
  fresh delta polling instead.

## LibreCrawl REST vs MCP server

These terms refer to separate transport paths and must not be conflated.

| Component | Current use | Connection |
| --- | --- | --- |
| LibreCrawl REST application | Used by audit pipeline | `LibreCrawlClient` -> `LIBRECRAWL_URL` (normally port 5080) |
| `librecrawl/mcp-server` FastMCP wrapper | Not used in current runtime | Would normally expose MCP HTTP/stdio (default port 5081) |
| Internal Copilot ToolRegistry | Used by AI Copilot today | Direct, project-scoped read-only Python/DB handlers |

The internal registry is intentionally transport-neutral. A later controlled
MCP adapter can reuse the same tool authorization/validation model rather than
letting an LLM obtain unscoped database or crawler access.

The recommended future write/live design is:

```text
AI recognizes a fresh/live action may help
  -> explains expected scope/cost and asks for explicit approval
  -> server records approved command/job
  -> controlled MCP/REST adapter invokes the selected live action
  -> worker persists results as a new audit/observation
  -> dashboard and Copilot read the new stored result
```

Never make a normal page open or ordinary chat message silently start a crawl
or external provider refresh.

## Performance contracts

| Surface | Contract |
| --- | --- |
| Initial project load | Render lightweight shell and active-audit state first; do not eager-load all history/rows |
| Trends | Fetch/card data and load Chart.js only after Trends opens; per-period memory cache TTL is 60 seconds and invalidates after a completed audit |
| Keywords | Lazy tab request; server-page 25 rows at a time |
| Audit History | Cursor pagination of 10 snapshots; index `(client_id, created_at, id)` |
| Overview issues | IntersectionObserver/load on approach rather than initial project request |
| Health | Lazy fetch; SQL aggregates instead of loading every ranking row |
| Copilot | Cursor-paged messages, bounded model context, delta polling only while processing |

These are user-facing behavior contracts. A refactor that reintroduces eager
bulk queries or static/double-counted trend data should be treated as a
regression even if the UI still renders.

## Migration, deployment, and backfill notes

Relevant historic revisions:

- `j7e8f9a0b1c2_add_health_scores_and_copilot.py` - Health Score/Copilot
  tables.
- `k8f9a0b1c2d3_add_copilot_message_cursor_index.py` - chat cursor index.
- Existing daily metric composite indexes are sufficient for the comparable
  trend/chart release; no migration was added for that part.

Normal deployment when pulling a change that affects the worker or migrations:

```powershell
docker compose build web worker
docker compose run --rm web python -m flask --app manage.py db upgrade
docker compose up -d --force-recreate web worker
docker compose ps
```

Optional, one-project trend history backfill (costs only the selected Google
provider requests; does not crawl, report, or invoke AI):

```powershell
docker compose exec -T web python -m scripts.backfill_daily_trends --client-id 2 --dry-run
docker compose exec -T web python -m scripts.backfill_daily_trends --client-id 2 --days 455
```

Use the first command before the second. `455` covers the largest current 90
day plus previous-year comparison requirement.

## Verification and support checklist

### Automated coverage

- Full suite after trend completion: `python -m pytest tests -q` -> 58 passed.
- Trend tests cover equal windows, weighted CTR, sparse coverage, delayed GSC,
  audit observations, route contract, backfill ranges, and JavaScript syntax.
- Copilot coverage includes server context injection, response persistence,
  invocation trail, schema bounds, and chat history pagination.

### Release smoke test

1. Confirm Alembic reports `k8f9a0b1c2d3 (head)`.
2. Confirm web is up and worker is healthy.
3. Open a project with stored data; verify Overview shell renders before lazy
   modules.
4. Open Trends, choose 30/60/90, select a card, and check values, comparison
   labels, and chart observation table.
5. Open Keywords and Audit History; verify pagination/loading behavior.
6. Send a Copilot question with an available data source; verify it queues,
   resolves, shows a source chip, and records no new audit/provider action.
7. Verify an empty-data Project displays explicit absence states, not invented
   zeros or percentage changes.

## Known limits and planned extension points

- Chat is stored-data/read-only; no live provider refresh, audit launch, or
  data mutation from chat.
- The worker gives pending audits priority, so a Copilot reply may wait while
  audit work is busy.
- No streaming token response; UI uses polling and typing/progress state.
- No multi-conversation list/rename/archive UI yet.
- YoY only appears after sufficient daily stored history exists.
- Crawl/backlink charts can only show dates where a completed audit recorded an
  observation.

Natural Week 4 extensions are selective refresh with explicit user selection,
alerts, AI keyword suggestions, historical recommendation retrieval, and
exports. Any live/mutating AI feature must retain the approval, job audit, data
persistence, and cost-control boundary described above.

## Primary source files and commits

- `pipeline/services/trend_analysis.py`, `pipeline/app/static/js/project-trends.js`
  - comparable trends and chart behavior (`636afcd`).
- `pipeline/services/health.py` - Health Score v2 (`6548634`).
- `pipeline/services/copilot_agent.py`, `copilot_tools.py`,
  `tool_registry.py`, `copilot_history.py` - Agent and bounded data access
  (`6548634`, `49ab39d`).
- `pipeline/app/templates/project.html` and UI assets - Dashboard/Copilot UX
  (`cc14509`, `24d154f`, `db8a34d`, `636afcd`).
- `pipeline/services/librecrawl_client.py`, `pipeline/services/pipeline_runner.py`
  - current REST crawl path.

For client-facing operation, keep the companion guide in sync whenever a
feature changes what a client can click, what data the AI may use, or what a
chat action is permitted to do.
