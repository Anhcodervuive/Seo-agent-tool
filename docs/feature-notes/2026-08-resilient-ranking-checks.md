# Resilient DataForSEO Ranking Checks

**Delivered:** 25 August 2026

**Scope:** tracked-keyword accuracy, provider reliability, audit cost control, and diagnostics.

## Purpose and user-facing result

Tracked keyword positions are now collected through DataForSEO's Standard SERP
task workflow instead of sending one live SERP request at a time for every
keyword/target pair. The result displayed for a keyword now has three explicit
meanings:

| Result | Meaning | How it is counted |
| --- | --- | --- |
| **Position found** | The provider completed the check and the project/competitor domain was found in the top 100 organic results. | Ranked |
| **Not in top 100** | The provider completed the check, but did not return the target domain in the checked organic results. | Not ranking |
| **Checks unavailable** | DataForSEO or the search engine did not supply a usable result before the timeout. | Failed; never counted as “not ranking” |

The Keywords tab now has a **Checks unavailable** filter and counter. A failed
row shows `Unavailable` and a short provider-error hint instead of implying
that the website has no Google ranking.

## Data flow

```text
Tracked keywords × project/competitor targets
        -> up to 100 Standard SERP tasks per DataForSEO request
        -> task IDs stored temporarily in the active Snapshot
        -> bounded poll of DataForSEO Tasks Ready
        -> retrieve completed task result
        -> local domain matching (www/non-www/canonical-safe)
        -> Ranking row: found | not_found | failed
```

The task correlation state is saved in `Snapshot.notes` while the ranking stage
is running. If the audit worker stops after tasks were submitted, its recovered
job resumes the existing provider task IDs instead of submitting a duplicate
set. The temporary state is removed after the ranking stage finishes.

The Standard API accepts a maximum of 100 tasks in one submission. The code
uses this maximum as a safe batch boundary. It does **not** claim that a batch
turns 100 paid SERP checks into one paid check: normal DataForSEO per-task
pricing still applies. The savings come from avoiding redundant full-audit
retries and from using an asynchronous provider workflow designed for bulk
work.

DataForSEO documentation for the Standard task flow and error codes:

- [Google Organic task submission and retrieval](https://docs.dataforseo.com/v3/serp-google-organic-overview/)
- [Tasks Ready endpoint](https://docs.dataforseo.com/v3/serp/endpoints/)
- [DataForSEO status and error codes](https://docs.dataforseo.com/v3/appendix/errors/)

## Audit retry policy

The snapshot lifecycle now separates an unusable audit from an incomplete one.

- A required crawl failure can still make a snapshot **Failed** and eligible
  for the existing queue retry policy.
- A ranking provider failure produces a **Partial** snapshot. Successful crawl,
  GA4, GSC, backlink, and ranking rows remain available; the worker does not
  repeat the entire audit just to retry failed ranking calls.
- AI report generation is an optional final enhancement. If the AI provider
  rejects a report request (for example, a provider HTTP 404), the snapshot is
  **Partial** and the already-collected crawl/Google/DataForSEO data is not
  recollected automatically.

When the provider is healthy again, run **Ranking check only** to refresh just
the affected ranking data. This is the appropriate low-cost recovery action.

## Configuration

Both values have production-safe defaults and are documented in
[`pipeline/.env.example`](../../pipeline/.env.example).

```dotenv
DATAFORSEO_RANKING_POLL_SECONDS=10
DATAFORSEO_RANKING_MAX_WAIT_SECONDS=900
```

`DATAFORSEO_RANKING_POLL_SECONDS` is clamped to 5–60 seconds. The maximum wait
is clamped to 60–3600 seconds. At timeout, the unresolved rows are persisted as
**Checks unavailable** with `retryable: true` diagnostic context; they are not
silently converted to “not in top 100.”

No database migration is required. The existing `rankings.check_status` and
`rankings.error_message` columns are the durable source of the per-row result.

## Operational diagnostics

The audit worker now writes structured JSON log lines to Docker stdout. They
can be searched by `snapshot_id`, `client_id`, `ranking_check_id`, provider task
ID, target, keyword, device, location, endpoint, HTTP status, provider status
code, and retryability. No request headers or API credentials are logged.

Important events:

| Event | Use it for |
| --- | --- |
| `ranking.stage_started` / `ranking.stage_finished` | totals, counts, cost, transport, and whether the worker resumed an existing task state |
| `ranking.submission_started` / `ranking.submission_finished` | batch count and task acknowledgement outcome |
| `ranking.ready_poll_failed` | provider/list endpoint availability problem |
| `ranking.provider_failure` | exact failed keyword/target context and safe provider diagnostic |
| `ranking.enrichment_failed` | search-volume lookup problem without hiding the ranking result |
| `report.generation_failed` | AI report failure that did not cause data collection to run again |

Example support command:

```powershell
docker compose logs --since 24h worker | Select-String 'ranking\.provider_failure|ranking\.stage_finished|report\.generation_failed'
```

Run it from the `pipeline` directory. Share the matching log lines and the
Snapshot number with the technical team; never share `.env` contents.

## Deployment and verification

1. Deploy the application code and keep the two defaults above, or set an
   approved polling/timeout policy in the deployment environment.
2. Rebuild and restart both `web` and `worker`, because they use the same image.
3. No Alembic migration is needed for this feature.
4. Run a **Ranking check only** first on a non-critical project. Verify that
   progress changes from queueing to waiting/completed, the expected number of
   rows appears, and any provider failure lands in **Checks unavailable**.
5. If a report provider is unavailable, verify that a Full audit finishes as
   **Partial** and does not create a replacement full-audit job.

Regression verification included 72 automated tests, including Standard task
batching (100 + 1 task split), provider status `40101`, pending task handling,
local domain matching, failed/not-ranking separation, and partial snapshot
status handling.

## Known limits

- A Standard task may take time to complete because the search engine performs
  the requested search asynchronously. The live progress panel intentionally
  reports this waiting state instead of freezing the page.
- Search-engine-side errors can still happen. The product records them
  transparently and makes a ranking-only refresh the recovery path; it cannot
  force the upstream search engine to return a result.
- Existing historical rows are not rewritten. The stricter distinction applies
  to new checks after deployment; old Snapshots retain the status saved at the
  time they ran.

## Commit

`Harden ranking checks and audit retries`
