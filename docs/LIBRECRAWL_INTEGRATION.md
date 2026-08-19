# LibreCrawl Integration

The worker talks to LibreCrawl through `services/librecrawl_client.py`. The
web browser never calls the crawler directly. `LIBRECRAWL_URL`, request
timeout, polling interval, and maximum polls are configured for the worker
environment.

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
