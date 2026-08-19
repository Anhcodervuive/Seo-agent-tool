# Testing

Run the pipeline unit tests from the `pipeline` directory:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

The tests cover the LibreCrawl client contract, crawl payload normalization,
pipeline stage behavior, report contracts, queue helpers, status handling, and
snapshot deletion relationships.

Tests that call live GA4, GSC, DataForSEO, or LibreCrawl services should be
run separately with valid credentials. Unit tests must remain runnable without
those external services.
