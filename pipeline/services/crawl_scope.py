"""Build validated crawl scopes for project analysis runs."""

from urllib.parse import urljoin, urlsplit, urlunsplit

from services.site_urls import normalize_site_url


CRAWL_MODES = {"full", "selected_urls", "path", "reuse"}
MODE_ALIASES = {
    # Existing projects used ``selected`` for their saved path list.
    "selected": "path",
    "selected_paths": "path",
    "paths": "path",
}


def _split_values(value):
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = (value or "").replace(",", "\n").splitlines()
    return [str(item).strip() for item in items if str(item).strip()]


def _site_host(value):
    host = urlsplit(value).hostname or ""
    return host.lower().removeprefix("www.")


def _absolute_project_url(value, site_origin):
    """Normalize one user-supplied URL and keep it within the project site."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("A selected URL cannot be empty.")

    candidate = urljoin(f"{site_origin}/", raw)
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Invalid selected URL: {raw}")
    if parsed.username or parsed.password:
        raise ValueError("Selected URLs cannot contain username or password information.")
    if _site_host(candidate) != _site_host(site_origin):
        raise ValueError("Selected URLs must belong to the current project domain.")

    # Keep the exact project origin (for example, do not let a ``www`` alias
    # become an external URL to a crawler seeded at the non-www origin).
    site = urlsplit(site_origin)
    path = parsed.path or "/"
    return urlunsplit((site.scheme, site.netloc, path, parsed.query, ""))


def _project_paths(values, site_origin):
    paths = []
    for raw in values:
        candidate = raw.strip()
        if "://" in candidate:
            candidate = _absolute_project_url(candidate, site_origin)
            candidate = urlsplit(candidate).path or "/"
        if not candidate.startswith("/"):
            candidate = f"/{candidate}"
        normalized = candidate.rstrip("/") or "/"
        if normalized not in paths:
            paths.append(normalized)
    return paths


def build_crawl_scope(client, mode=None, targets=None):
    """Return a serializable crawl scope for a snapshot job.

    ``selected_urls`` is intentionally strict: it queues only the exact URLs
    supplied for that run and disables sitemap/link discovery. ``path`` uses
    the project-level saved path list and permits discovery inside those paths.
    """
    requested_mode = (mode or getattr(client, "crawl_mode", None) or "full").strip().lower()
    selected_mode = MODE_ALIASES.get(requested_mode, requested_mode)
    if selected_mode not in CRAWL_MODES:
        raise ValueError("Choose a valid crawl mode.")

    site_origin = normalize_site_url(client.domain)
    supplied_targets = _split_values(targets)

    if selected_mode == "reuse":
        return {"mode": "reuse", "site_origin": site_origin, "seed_urls": []}

    if selected_mode == "selected_urls":
        if not supplied_targets:
            raise ValueError("Add at least one URL for a Selected URLs crawl.")
        seed_urls = []
        for raw in supplied_targets:
            normalized = _absolute_project_url(raw, site_origin)
            if normalized not in seed_urls:
                seed_urls.append(normalized)
        return {
            "mode": "selected_urls",
            "site_origin": site_origin,
            "seed_urls": seed_urls,
            "discover_sitemaps": False,
            "allowed_urls": seed_urls,
        }

    if selected_mode == "path":
        path_values = supplied_targets or _split_values(getattr(client, "crawl_paths", None))
        if not path_values:
            raise ValueError("Add at least one folder or path for a Folder/Path crawl.")
        allowed_paths = _project_paths(path_values, site_origin)
        return {
            "mode": "path",
            "site_origin": site_origin,
            "seed_urls": [urljoin(f"{site_origin}/", path.lstrip("/")) for path in allowed_paths],
            "allowed_path_prefixes": allowed_paths,
            "discover_sitemaps": True,
        }

    return {
        "mode": "full",
        "site_origin": site_origin,
        "seed_urls": [site_origin],
        "discover_sitemaps": True,
    }
