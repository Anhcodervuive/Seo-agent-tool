# Complete Broken-Link Validation and Keyword Language Selection

**Completed:** 25 August 2026
**Requirements:** 38 (Broken Link Report), 39 (keyword language dropdown)

## User-facing result

The Broken Links Report no longer depends only on URLs that happened to be
inside LibreCrawl's crawl queue. After a Full audit finishes crawling, the
worker checks unresolved HTTP(S) targets and stores both HTTP failures and
network failures. The report is paginated, explains the evidence, and exports
the complete result set to CSV.

Project creation and editing now use a supported language dropdown for every
tracked keyword and for the bulk-add defaults. Keyword Research and Project
Settings read the same language catalogue, so one workflow cannot save a code
that the other workflow rejects.

## How to use it

### Broken links

1. Run a **Full audit** with a real crawl. A Ranking-only run does not inspect
   website links, and **Reuse previous crawl** copies the previous evidence.
2. Open **Audit History**, then **View Data** for the new Snapshot.
3. Open **Links** and review **Broken Links Report**.
4. Read the status and Evidence columns:
   - `404 Not Found`, `410 Gone`, other 4xx, or 5xx are HTTP responses;
   - `Timeout`, `DNS Error`, `SSL Error`, connection failures, and redirect
     failures mean the target could not be verified by the worker;
   - `403 Forbidden` can mean the destination blocks automated requests. It
     should be manually checked before removing the link.
5. Select **Export all CSV** for every matching occurrence. CSV is not limited
   to the current 50-row page.

### Keyword language

1. Open **Add Project** or **Settings** for an existing Project.
2. Open **Tracking**.
3. Choose a Language in **Batch add keywords**, or choose it independently on
   each keyword row.
4. Save the Project. The language is used together with keyword, country,
   device, and domain when later ranking checks are submitted.

An old unsupported language code is shown as a legacy option in Edit Project.
The user must choose a supported replacement before saving; existing rows are
not deleted when server-side validation fails.

## Data flow

```text
Full audit
  -> LibreCrawl REST crawl completes
  -> reuse target statuses for pages LibreCrawl fetched
  -> group unresolved links by normalized target URL
  -> bounded concurrent HEAD checks
  -> streamed GET fallback when HEAD reports an error
  -> store one result on every source-page occurrence
  -> Snapshot > Links report and full CSV export
```

The validator does not run in the browser and does not use
`librecrawl/mcp-server`. It runs in `seo_agent_worker` after the active REST
crawl completes and before its export is persisted.

Important implementation details:

- Every normalized unresolved target is requested once, even when it appears
  on many source pages.
- Global concurrency and per-host concurrency are bounded separately. The
  per-host limit reduces false `429` responses and avoids overloading one site.
- HEAD is cheap, but servers sometimes implement it incorrectly. An error
  response is therefore verified with a streamed GET that does not download
  the full body.
- Redirects are followed and the final URL and redirect count are retained.
- Private, loopback, link-local, multicast, reserved, and unspecified network
  targets are not requested by default. This is an SSRF safety boundary.
- A failed target never aborts the audit. Its error is recorded as report
  evidence instead.

## Stored fields and migration

Migration `o2c3d4e5f6a7` adds nullable evidence fields to
`crawl_page_links`:

- final URL;
- status source;
- error type and detail;
- checked timestamp;
- response time; and
- redirect count.

The migration is backward-compatible. Existing rows remain valid and existing
4xx/5xx values continue to display. Old Snapshots are not silently rechecked;
run a new Full audit to collect complete external/out-of-scope link evidence.
Reuse-previous-crawl intentionally copies the old evidence and does not contact
link targets again.

## Configuration

| Variable | Default | Purpose |
| --- | ---: | --- |
| `BROKEN_LINK_VALIDATION_ENABLED` | `true` | Enable unresolved-target checks after a crawl |
| `BROKEN_LINK_VALIDATION_WORKERS` | `12` | Maximum total concurrent checks |
| `BROKEN_LINK_VALIDATION_PER_HOST_WORKERS` | `3` | Maximum concurrent checks to one hostname |
| `BROKEN_LINK_VALIDATION_TIMEOUT_SECONDS` | `10` | Connect/read timeout per request |
| `BROKEN_LINK_ALLOW_PRIVATE_HOSTS` | `false` | Development-only override for private/local targets |

Keep private-host validation disabled in production. Increase concurrency only
after observing worker resources and destination rate limiting.

## Operations and logs

The worker emits one JSON event after each validation stage:

```text
"event": "crawl.link_validation.completed"
```

It includes Snapshot/crawl IDs, total link rows, unique targets, statuses reused
from crawl data, checked targets, HTTP failures, unreachable targets, skipped
targets, configured limits, and elapsed milliseconds. The same summary is
stored under `snapshot.notes.crawl_quality.link_validation`.

Example operational check:

```bash
docker logs --timestamps --since 2h seo_agent_worker 2>&1 \
  | grep 'crawl.link_validation.completed'
```

## Verification

Run from `pipeline`:

```powershell
python -m unittest tests.test_link_validation tests.test_broken_link_report tests.test_project_settings_flow -v
python -m unittest discover -s tests -v
python -m flask --app manage.py db heads
python -m flask --app manage.py db upgrade
```

The automated coverage verifies target deduplication, status reuse, network
errors, HEAD-to-GET fallback, pagination, complete CSV output, supported
language persistence, and safe rejection without replacing existing keywords.

## Known limitations

- A destination can intentionally return `403`/`429` to automated clients even
  when it opens in a person's browser. The report preserves that response so a
  user can make the final decision.
- Results describe reachability at audit time. A later destination change
  requires a new Full audit.
- JavaScript-generated links are present only when LibreCrawl rendered and
  exported them; the validator cannot check a link it was never given.
