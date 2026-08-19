# Week 3: Health Score v2 and AI Copilot

**Status:** Delivered and verified on 19 August 2026

This milestone upgrades the project health indicator from a one-off dashboard
calculation to a versioned historical record, and replaces the Copilot
placeholder with a secure, read-only chat agent.

## What users can do

### Project Health Score

Open **Project → Overview**. The Health Score card shows the latest completed
full crawl's score, label, confidence, and a breakdown of the available
pillars. Existing projects are backfilled once; future full audits persist a
new score after their normal stages finish.

The score is 0–100 and reweights only data that is actually available. It does
not turn missing GA4/GSC/ranking/backlink data into a misleading zero.

| Pillar | Nominal weight | Stored source | Calculation |
| --- | ---: | --- | --- |
| Technical | 35% | Crawl pages and issues on the snapshot | Weighted issue density per crawled page |
| Organic | 30% | `ga4_daily_metrics`, `gsc_daily_metrics` | Two equal 30-day stored-data windows; GA4 sessions, GSC clicks and CTR |
| Keywords | 20% | Project-owned `rankings` rows | Ranking coverage, top-10 share and average position |
| Backlinks | 15% | Project-owned `backlink_history` row | Referring-domain change vs preceding audit, or a labelled baseline |

Competitor ranking and backlink rows are explicitly excluded from the project
score. Confidence is the weighted amount of usable data; it is shown beside
the score so an early project is not mistaken for a fully observed one.

`health_scores` retains the snapshot ID, formula version (`v2`), component
details, factors and calculation time. That preserves historical meaning even
if a future formula is introduced.

### AI SEO Copilot

The Overview chat accepts a question and queues a short background Copilot
run. The input is disabled while the run is pending/running; the browser polls
only while there is work. Refreshing the page restores the conversation and
its completed responses.

Copilot can read:

- stored GA4 daily data;
- stored GSC daily data;
- project keyword rankings and movement;
- project backlink history;
- the latest crawl issue groups;
- stored competitor insights; and
- the latest persisted Health Score.

It cannot start an audit, refresh a provider, write project data, or access a
project selected by the model. The UI intentionally says **stored-data
assistant**: this release avoids unexpected API costs and has no external side
effects.

## Data flow and safety boundary

```text
Browser question
  -> POST /project/<id>/copilot/messages (access check)
  -> copilot_conversations + copilot_messages + pending copilot_runs
  -> audit worker claims one run
  -> OpenRouter function-call loop (max 4 turns / 6 tool calls)
  -> server-injected ToolContext(client_id, user_id, run_id)
  -> read-only DB tool result
  -> copilot_tool_invocations audit trail + assistant message
  -> browser polling shows the response
```

The browser route authorizes the signed-in user before it creates or reads a
conversation. `client_id` is never part of a tool schema and is never accepted
from a model tool call. Each schema rejects unknown fields and caps date ranges
at 90 days and list responses at 100 rows. Tool outputs are bounded and the
agent has hard turn/tool-call limits.

`services/tool_registry.py` is transport-neutral. The same contracts can be
wrapped by a future MCP server without moving authorization into the model or
duplicating business logic. `services/copilot_tools.py` is the only layer that
knows how to query the stored SEO tables. `services/copilot_provider.py` is
the isolated OpenRouter adapter.

## Configuration and deployment

Copilot needs the existing `OPENROUTER_API_KEY` plus a configured OpenRouter
model that supports function calling. The app keeps using the global/project
AI model setting. If the provider is missing or rejects tool calls, the run is
marked failed with a visible, safe error; the audit worker remains healthy.

Migration: `j7e8f9a0b1c2_add_health_scores_and_copilot.py`.

For a deployment with existing snapshot history:

```powershell
docker compose build web worker
docker compose run --rm web python -m flask --app manage.py db upgrade
docker compose up -d --force-recreate web worker
docker compose exec -T web python -m scripts.backfill_health_scores
```

The last command is idempotent: it upserts one v2 score per snapshot that has
crawled pages. It does not call GA4, GSC, DataForSEO, LibreCrawl, or OpenRouter.

## Verification performed

- Full automated suite: `python -m pytest tests -q` → **50 passed**.
- Unit/integration coverage verifies Health Score v2 persistence, exclusion of
  competitor ranking rows, agent tool context injection, assistant response
  persistence, invocation audit trail, schema limits and unknown-argument
  rejection.
- PostgreSQL migration applied successfully; `health_scores`, all four
  Copilot tables, and Alembic revision `j7e8f9a0b1c2` were confirmed.
- Web and worker were rebuilt and recreated after migration.
- A temporary end-to-end OpenRouter tool-call smoke test completed using the
  configured model: it called `get_project_health`, returned the stored score,
  and then its temporary conversation, run, messages, and invocation records
  were deleted.

## Known limits and next work

- A first audit may lack two equal 30-day periods, so Organic is omitted and
  confidence is lower instead of inventing a trend.
- GSC has a normal reporting delay; the comparator uses its latest stored date
  at or before the audit date.
- The initial chat surface keeps one active conversation per user/project. A
  conversation list, rename/archive, and export belong naturally to Week 4.
- Tools deliberately use stored data. Selective refresh and any write-capable
  tool require a separate approval and cost-control design in Week 4.
