# Keyword Research Workspace (Requirement 37)

## Purpose

The **Keyword Research** workspace is a standalone discovery tool for finding and evaluating keywords before they are tracked in a project. It is available from the main navigation beside **One-Page Audit**.

It deliberately does **not** create an audit snapshot, alter a project Health Score, change GA4/GSC trends, or change existing ranking history. This keeps exploratory research separate from the evidence collected during an audit.

## How to use it

1. Open **Keyword Research** from the main navigation.
2. Choose a country and language. Location is required because search demand and difficulty are market-specific.
3. Select a research mode:
   - **Single keyword**: enter one seed keyword to receive related keyword ideas, questions, and Google Autocomplete suggestions.
   - **Multiple keywords**: paste keywords separated by a new line, comma, or semicolon to evaluate the supplied terms only.
4. Optionally choose a project. Selecting a project does not track anything yet; it makes the later handoff quicker.
5. Start research. The request is placed in the background queue, so the browser remains responsive. The detail page updates its progress automatically.
6. Review search volume, Keyword Difficulty (KD), CPC, competition, intent, related questions, and autocomplete ideas. Download the result set as CSV if required.
7. Use **Add to Track** beside a useful keyword and choose a project. The application prevents duplicate tracked keywords for the same project, location, language, and device.
8. Run a later project audit to collect the keyword's first ranking position. Research itself never invents a ranking record.

## Business-fit review and relevance controls

Provider-related keywords are discovery candidates, not a recommendation that every row belongs to the project. A broad seed can legitimately surface a neighbouring intent; for example, `mortgage` may be irrelevant for a cash-house buyer but essential for a mortgage broker.

The workspace therefore does not apply risky global exclusions or infer business relevance from an AI guess. Instead, each saved research run has optional, user-controlled criteria:

- **Focus terms**: a keyword containing one of these phrases is labelled **Aligned**.
- **Exclude terms**: a keyword containing one of these phrases is labelled **Excluded**.
- **Input**: an exact keyword supplied by the user remains marked as the input.
- **Needs review**: a candidate does not match either list after criteria have been set.
- **Not assessed**: no focus/exclude criteria have been set for the run yet.

The match phrases are case-insensitive text matches. They are transparent local labels, not provider metrics, AI scores, or automatic deletions. An Excluded keyword stays visible and can still be added to tracking when an operator decides it is appropriate.

Focus and exclude terms can be supplied before the run or edited on its detail page. Editing them reclassifies the already saved rows immediately; it makes no DataForSEO request and does not change Volume, KD, snapshots, trends, Health Score, or existing tracking records.

For example, a cash-house buying project could use focus terms `sell house, cash buyer` and exclude terms `mortgage, buy to let`. This moves relevant opportunities to the top while leaving neighbouring terms available for an informed review.

## Data returned

### Single keyword mode

The workspace combines several provider responses so that a seed query is useful for planning rather than only being a metrics lookup:

- Related keyword ideas and suggestions.
- Search volume, Keyword Difficulty, CPC, competition, and intent when the provider returns them.
- People Also Ask questions from Google's organic SERP response.
- Google Autocomplete suggestions.

### Multiple keyword mode

The workspace measures only the submitted keywords. It returns the available search volume, KD, CPC, competition, and intent for each one; it does not expand the list with unrelated discovery suggestions.

## Accuracy and honest empty states

Search volume is the provider's current monthly estimate for the selected country and language. It should be used for prioritisation, not presented as an exact count of future searches. Keyword Difficulty is the provider's 0-100 estimate of ranking difficulty.

The application never turns a missing provider response into `0`. A missing metric remains visibly unavailable. This avoids making a keyword look easy, low-volume, or invalid merely because a provider section was delayed or unavailable.

Research is reported as one of these states:

- **Completed**: all requested sources returned usable data.
- **Completed with warnings**: usable results were saved, but one or more optional sources did not return data. The page shows the affected section and a retryable warning.
- **Failed**: no usable research data could be saved. The stored message identifies the provider issue without changing project data.

## Performance, cost, and caching policy

The system runs independent provider requests concurrently, stores the durable result once, and serves the saved result page thereafter. Reopening a completed, equivalent request from the same user within **60 minutes** reuses it by default. Select **Refresh provider data** to bypass that cache.

The default maximum bulk input is **250 keywords**. The hard provider-safe ceiling is **1,000 keywords**. Single-keyword discovery stores the best provider candidates up to the configured discovery limit (default **100**, maximum **250**). The result table reads those saved rows with server-side search, filters, sorting, and pages of **25** by default rather than rendering every candidate at once. CSV export intentionally includes every saved keyword row. These bounds protect response time, browser usability, and API cost while remaining configurable by deployment.

Keyword Research is processed after audit and Copilot jobs, and before the low-priority deferred ranking reconciliation queue. A slow research provider therefore cannot block a project audit.

## Provider integration

The integration uses DataForSEO live endpoints:

- [Keyword Ideas](https://docs.dataforseo.com/v3/dataforseo_labs-google-keyword_ideas-live/) and [Keyword Suggestions](https://docs.dataforseo.com/v3/dataforseo_labs-google-keyword_suggestions-live/) for related terms.
- [Keyword Overview](https://docs.dataforseo.com/v3/dataforseo_labs-google-keyword_overview-live/) and [Bulk Keyword Difficulty](https://docs.dataforseo.com/v3/dataforseo_labs-google-bulk_keyword_difficulty-live/) for keyword metrics.
- [Google Organic Live Advanced](https://docs.dataforseo.com/v3/serp-google-organic-live-advanced/) for People Also Ask items.
- [Google Autocomplete Live Advanced](https://docs.dataforseo.com/v3/serp-google-autocomplete-live-advanced/) for autocomplete suggestions.

Real responses depend on the connected DataForSEO account, available credits, country/language availability, and provider response time. The workspace records provider warnings per section so operations can distinguish an unavailable provider result from a true zero metric.

## Persistence and deployment

The feature adds two durable tables:

- `keyword_research_runs`: input, progress, status, warnings, cost, and ownership.
- `keyword_research_results`: typed keyword, question, and autocomplete results.

The business-fit refinement adds the local criteria on the run and a fit label plus matched phrases on each keyword result. Existing research stays compatible: rows created before this refinement show as **Not assessed** until criteria are applied.

Migration revisions:

- `m0a1b2c3d4e5` — **Add durable keyword research runs and results**.
- `n1b2c3d4e5f6` — **Add user-controlled business-fit labels to keyword research**.

The normal deployment migration container applies this revision automatically. No manual database command is required beyond the standard deployment flow.

Relevant optional environment settings:

```env
KEYWORD_RESEARCH_MAX_BULK_KEYWORDS=250
KEYWORD_RESEARCH_DISCOVERY_LIMIT=100
KEYWORD_RESEARCH_RESULT_PAGE_SIZE=25
KEYWORD_RESEARCH_CACHE_MINUTES=60
KEYWORD_RESEARCH_STALE_MINUTES=20
```

## Verification performed

- Applied the migration against the local Docker PostgreSQL database and confirmed the new revision and tables.
- Started the web and worker containers successfully after the schema update.
- Confirmed `/keyword-research` is protected by the existing login flow.
- Added focused tests for provider result merging, metric mapping, input validation, durable worker processing, partial provider outcomes, route access, CSV/state handling, Add-to-Track behaviour, local business-fit reclassification, and server-side filtered pagination.
- Ran the full automated suite: **98 tests passed**.

The automated provider tests use controlled response fixtures to avoid spending a live API account during local verification. A controlled staging request with valid DataForSEO credentials remains the appropriate final check of account access and provider billing.
