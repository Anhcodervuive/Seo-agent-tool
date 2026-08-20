# LibreCrawl Integration

The worker talks to LibreCrawl through `services/librecrawl_client.py`. The
web browser never calls the crawler directly. `LIBRECRAWL_URL`, request
timeout, polling interval, and maximum polls are configured for the worker
environment.

## REST crawler integration vs MCP server

The active pipeline uses the LibreCrawl **REST** application (normally
`LIBRECRAWL_URL` on port `5080`) to authenticate, start a crawl, poll it, and
import its finished export. This is the path used by a Full audit.

`librecrawl/mcp-server` is a separate FastMCP wrapper (default port `5081`).
It is present in this repository but is **not** started by the pipeline Docker
Compose file and is **not** on the current dashboard or AI Copilot execution
path. The current Copilot uses an internal, project-scoped read-only ToolRegistry
against persisted database data; it does not call the MCP server or start a
crawl from chat.

If a future AI feature needs a live crawl or site check, keep the sequence
explicit: show the user scope/cost, record approval, submit a controlled job,
persist the result, then let dashboard/Copilot read that stored result. Do not
make a normal page view or chat question silently trigger the MCP server.

The client handles authentication, crawl creation, polling, and provider
errors. Once a crawl completes, `services/crawl_data.py` validates and
normalizes the export before database persistence.

For local Docker usage, make sure the worker can reach the configured crawler
host. A URL that works in the browser or Flask container may not be reachable
from the worker container because Docker networking changes `127.0.0.1`.

Useful checks:

```powershell
docker compose ps
docker compose logs worker
```

If a crawl is incomplete, inspect the snapshot status, run notes, and
`crawl_quality` counters before retrying the audit.
